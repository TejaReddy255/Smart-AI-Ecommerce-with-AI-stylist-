import streamlit as st
import pandas as pd
from config import settings
from utils import cart,orders,mailer 
from genAI import query_intent
from train_model.build_index import build_index
from train_model import search_engine
from genAI import mail_generation
from genAI.stylist import generate_stylist_outfit
import uuid
from datetime import datetime, timezone 
import os,re



def initialize_session_state():
    """ This function initialize the session state"""
    if 'page' not in st.session_state:
        st.session_state.page ='search'
    if 'cart' not in st.session_state:
        st.session_state.cart=[]
    if 'order_details' not in st.session_state:
        st.session_state.order_details ={}
    if 'search_results' not in st.session_state:
        st.session_state.search_results=(None,[])
    if 'catalog_stats' not in st.session_state:
        st.session_state.catalog_stats={}
    
    
    

@st.cache_data
def load_catalog():
    """This function loads the data file into cache"""
    df = pd.read_csv(settings.DATA_DIR)
    df['img_path'] = df['id'].apply(
        lambda x:os.path.join(settings.IMAGE_DIR,f"{x}.jpg")
    )
    df= df[df['img_path'].apply(os.path.exists)].reset_index(drop=True)
    return df

@st.cache_data
def get_catalog_stats(catalog_df):
    """ This function filters the unquie values of gender,masterCategory,subCategory,articleType,baseColour coloumns of data csv file """
    stats={}
    for col in ['gender','masterCategory','subCategory','articleType','baseColour']:
        stats[col] =  catalog_df[col].dropna().unique().tolist()
    return stats


@st.cache_resource
def ensure_index_and_load_search_engine():
    """ This function loads the index into cache and initializes search function"""
    with st.spinner("building or loading product index... This may take a moment"):
        if not os.path.exists(os.path.join(settings.INDEX_DIR,'faiss_clip.index')):
            st.info('Product index not found. Building it now..')
            #build_index()
            st.success('product index built successfully!')
        else:
            st.success('product index loaded')
    #it should return search engine    
    return search_engine

def load_row(r):
    df = pd.read_csv(settings.DATA_DIR)
    df['img_path'] = df['id'].apply(
        lambda x:os.path.join(settings.IMAGE_DIR,f"{x}.jpg")
    )
    df= df[df['img_path'].apply(os.path.exists)].reset_index(drop=True)
    return df.loc[r]
      
def get_product_image(product_id):
    """ This function verifies if the image path is exist or not """
    img_ext=[".jpg",".jpeg",".png",".webp"]
    for ext in img_ext:
        img_path = os.path.join(settings.IMAGE_DIR,f"{product_id}{ext}")
        if os.path.exists(img_path):
            return img_path
    return None


def navigate_to(page):
    """ This function helps to navigate between pages """
    st.session_state.page=page 
    st.rerun()

def handle_search_from_state():
    q = st.session_state.get("search_input", "")
    handle_search(q)

def handle_search(search_query):
    """ This function is a helper function use to handle search """
    if not search_query:
        st.warning('please enter a search query.')
        return
    with st.spinner('searching for products....'):
        try:
            if not st.session_state.catalog_stats:
                st.session_state.catalog_stats=get_catalog_stats(load_catalog())
            
            parsed_intent = query_intent.parse_intent_with_gemini(search_query, st.session_state.catalog_stats)
            
            primary, recommendations =st.session_state.search_engine.search_primary_and_recommendations(
                              search_query,parsed_intent=parsed_intent
                         )            
            st.session_state.search_results=(primary,recommendations)

            if  primary is None and not recommendations:
                st.warning('No products found matching query')
        except Exception  as e:
            st.error(f'Error during search:{e}')    

def render_sidebar():
    """ This function renders the sidebar for search page"""
    
    st.sidebar.markdown(
        "<h2 style='color:#1f212b; font-size: 24px'> 🛒 Search & cart </h2>", unsafe_allow_html=True
    )

    search_query = st.sidebar.text_input(
        "Search for products",
        placeholder="e.g, men's red t-shirt under ₹1000",
        key ='search_input',
        on_change=handle_search_from_state
    )
    col1,col2 = st.sidebar.columns(2)
    with col1:
        if st.button('🔍 Search',key='search_button', use_container_width=True):
            handle_search(search_query)
        
    with col2:
        if st.button(f"🛒 Cart ({cart.cart_count(st.session_state.cart)})", use_container_width=True):
            navigate_to('cart')
     
    st.sidebar.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
    if st.sidebar.button('♻️ Rebuild Index(Optional)',key='rebuild_index_button', use_container_width=True):
            with st.spinner('Rebuildling product index... This will take a while'):
                build_index()
            st.cache_resource.clear()
            st.session_state.search_engine = ensure_index_and_load_search_engine()
            st.sidebar.success('Index rebuilt successfully')

def render_primary_product(product):
    """ This function renders the best match product"""
    if not product:
        return
    st.subheader('Best Match')
    col1,col2 = st.columns([1,2])

    with col1:
        img_path = get_product_image(product['id'])
        if img_path:
            st.image(img_path,use_column_width = True)
        else:
            st.write('Image not available')
    with col2:
            st.markdown(f"**{product['name']}**")
            st.write(f"Category: {product['masterCategory']} > {product['subCategory']} > {product['articleType']}")
            st.write(f"Color: {product['color']}")
            st.write(f"Price: {product['price']}")
            if st.button('View Details',key= f"view_{product['id']}"):
                st.session_state.current_view_product = product
                navigate_to("product_detail")



def render_recommendations(recommended_products):
    """ This function renders the recommendations """
    if  not recommended_products:
        return
    st.markdown("⭐Recommended for You")

    st.markdown("""
        <style>
            .product-card {
                border: 1px solid #e6e6e6;
                border-radius: 12px;
                padding: 16px;
                background-color: #fafafa;
                min-height: 350px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                box-shadow: 2px 2px 8px rgba(0,0,0,0.05);
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .product-card:hover {
                transform: scale(1.03);
                box-shadow: 2px 4px 12px rgba(0,0,0, 0.15);
            }
            .product-img img {
                height: 180px;
                width: 100%;
                object-fit: cover;
                border-radius: 4px;
            }
            .product-info {
                text-align: center;
                margin-top: 10px;
                display: flex;
                flex-direction: column;
                margin-bottom: 16px
            }
            .product-name {
                height: 30px
            }
            .product-price {
                color: #2e7d32;
                font-weight: 500;
                font-size: 16px;
            }
            .button-wrapper {
                text-align: center
            }
        </style>
    """, unsafe_allow_html=True)

    cols = st.columns(3) 
    for i,product in enumerate(recommended_products):
        with cols[i%3]:          

            img_path = get_product_image(product['id'])
            if img_path: 
                st.image(img_path,use_column_width=True) 
            else:
                st.image("https://via.placeholder.com/150", caption="No Image", use_column_width=True)
            
            st.markdown(
                f"""
                <div class="product-info">
                    <strong class="product-name">{product['name']}</strong><br>
                    <div class="product-price">{product['price']:.2f}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
              
            if st.button("View details",key=f"view_rec_{product['id']}"):
                st.session_state.current_view_product=product
                navigate_to("product_detail")
   
        
def render_search_page():
    """ This function renders the search page """
    
    st.markdown("<h1 style='font-size: 36px'>StyleScope: AI Product Search 🛍️</h1>" , unsafe_allow_html=True)
    render_sidebar()
    primary_product,recommended_products =st.session_state.search_results
    render_primary_product(primary_product)
    render_recommendations(recommended_products)
   

def render_back_to_search():
    st.markdown('---')

    if st.button('Back To Search'):
        navigate_to('search')   

def render_product_detail_page():
    """ This renders the product detail page with AI stylist recommendations """
    
    product = st.session_state.current_view_product
    if not product:
        st.warning("No product selected to view details. Returning to search.")
        navigate_to('search')
        return
    
    st.title(product['name'])
    col1, col2 = st.columns([1, 2])

    with col1:
        img_path = get_product_image(product['id'])
        if img_path:
            st.image(img_path, use_column_width=True, caption=product['name'])
        else:
            st.info("Image not available")

    with col2:
        st.markdown('### Product Details')
        st.write(f"**Category:** {product['masterCategory']} > {product['subCategory']}")
        st.write(f"**Article Type:** {product['articleType']}")
        st.write(f"**Color:** {product['color']}")
        st.metric(label="Price", value=f"₹{product['price']:,}")

        st.markdown('### Your Selection')

        size_options = cart.size_options_for(product)
        selected_size = st.selectbox("Select Size", size_options, key='product_size')
        quantity = st.number_input('Quantity', min_value=1, value=1, step=1, key='product_qty')

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🛒 Add to Cart", key="add_to_cart_detail", use_container_width=True):
                item = {
                    "id": product['id'],
                    "title": product['name'],
                    "price": product['price'],
                    "size": selected_size,
                    "qty": quantity,
                    "image": img_path
                }
                cart.add_to_cart(st.session_state.cart, item)
                st.success(f"🎉 Success! {quantity} x {product['name']} added to your cart.")
        with col_btn2:
            if st.button("Go to Cart", key="go_to_cart", use_container_width=True):
                navigate_to('cart')

    # ------------------------------
    # AI Stylist “Shop the Look” Section
    # ------------------------------
    st.markdown("---")
    st.subheader("🕺💃 Shop the Look - AI Stylist Recommendations")

    try:
        outfit = generate_stylist_outfit(product,load_catalog(), st.session_state.catalog_stats)
    except Exception as e:
        outfit = None
        st.error(f"Error generating outfit: {e}")

    if outfit:
        cols = st.columns(len(outfit))
        for idx, item in enumerate(outfit):
            with cols[idx]:
                
                img_path = get_product_image(item['id'])
                if img_path:
                    st.image(img_path, use_column_width=True)
                st.markdown(f"**{item['productDisplayName']}**")
                st.markdown(f"{item['articleType']}")
                st.markdown(f"Price: ₹{item['price_inr']}")

        # Add All to Cart Button
        if st.button("🛒 Add All to Cart (Complete Outfit)"):
            # Add anchor product + stylist recommendations to cart
            # Assuming same size for all recommended items as anchor product size
            items_to_add = [{
                "id": product['id'],
                "title": product['name'],
                "price": product['price'],
                "size": selected_size,
                "qty": quantity,
                "image": img_path
            }]
            for rec_item in outfit:
                rec_img_path = get_product_image(rec_item['id'])
                items_to_add.append({
                    "id": rec_item['id'],
                    "title": rec_item['productDisplayName'],
                    "price": rec_item['price_inr'],
                    "size": selected_size,  # You may want to adjust size logic here
                    "qty": 1,
                    "image": rec_img_path
                })

            for it in items_to_add:z
                cart.add_to_cart(st.session_state.cart, it)
            st.success(f"🎉 Added complete outfit ({len(items_to_add)} items) to your cart!")
    else:
        st.info("No complementary items found for this look.")

    render_back_to_search()
def render_cart_page():
    st.title("Your cart")

    if not st.session_state.cart:
        st.info("Your cart is empty")
        render_back_to_search()
        return
    total = cart.cart_total(st.session_state.cart)

    for idx, item in enumerate(st.session_state.cart):
        cols = st.columns([1, 2, 1])
        with cols[0]:
            if item.get("image"):
                st.image(item['image'], width=100)
        with cols[1]:
            st.write(f"**{item['title']}**")
            st.write(f"Size: {item['size']} | Qty: {item['qty']} | Rs{item['price']} each")
        with cols[2]:
            if st.button("Remove", key=f"remove_{idx}"):
                cart.remove_from_cart(st.session_state.cart, idx)
                st.rerun()
    st.markdown(f"### Total : Rs{total:.2f}")

    if st.button("Proceed to checkout"):
        navigate_to("checkout")
    
    render_back_to_search()

def  render_checkout_page():
    st.title("Checkout")

    with st.form("checkout_form"):
        name = st.text_input("Full name")
        email = st.text_input("Email")
        address = st.text_area("Shipping address")
        submitted = st.form_submit_button("Place Order")

        if submitted:
            if not name or not email or not address:
                st.warning("Please complete all fields.")
                return

            returning = orders.is_returning_customer(email)
            totals = orders.compute_totals_with_discounts(st.session_state.cart, returning)

            #order_id = str(uuid.uuid4())
            # "order_id": order_id,
            # "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            order = {
                "customer_name": name,
                "email": email,
                "address": address,
                "subtotal": totals['subtotal'],
                "discount_amount": totals['discount_amount'],
                "discount_breakdown": totals["discount_breakdown"],
                "total": totals['total'],
                "items": st.session_state.cart
            }

            try:
                order = orders.save_order(order)
               
            except Exception as e:
                st.error(f"Failed to save order: {e}")
                return

            content, err = mail_generation.generate_order_email_content(order, returning)

            if content:
                ok, mode = mailer.send_order_email(order, email, content)
                if not ok:
                    st.warning(f"Email could not be sent (mode: {mode})")
            else:
                st.warning(f"Email content generation failed: {err}")
            

            st.session_state.order_details = order
            st.session_state.cart = []
            navigate_to('order_placed')



def render_order_placed_page():
    """
    Shows a  confirmation page after a successful order.
    """
    order = st.session_state.get("order_details", {})
    if not order:
        # Handle the case where no order details are available
        st.warning("No recent order found. Please start a new search.")
        st.button("Back to Search", on_click=lambda: navigate_to("search"))
        return

    st.header("🎉 Thank you for your order! 🎉")
    st.success("Your order has been placed successfully!")

    
    with st.container(border=True):
        st.subheader("Order Details")
        st.markdown(f"**Order ID:** `{order['order_id']}`")
        st.markdown(f"**Order Date:** {order.get('order_date', 'N/A')}")
        st.markdown(f"**Customer Name:** {order['customer_name']}")
        st.markdown(f"**Email:** {order['email']}")
        st.markdown(f"**Shipping Address:** {order['address']}")

    
    st.markdown("---")

  
    with st.container(border=True):
        st.subheader("Order Summary")
        
       
        st.markdown("**Items**")
        for item in order['items']:
            st.markdown(
                f"- **{item['qty']}x** {item['title']} ({item['size']}) - Rs {item['price']:.2f}"
            )

        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("Subtotal:")
           
            if order.get("discount_breakdown"):
                for d in order["discount_breakdown"]:
                    st.markdown(f"- {d['name']}:")
                st.markdown("Discount:")
            else:
                st.markdown("Discount:")
            st.markdown("Total Paid:")
        with col2:
            st.markdown(f"**₹. {order['subtotal']:.2f}**")
            if order.get("discount_breakdown"):
                for d in order["discount_breakdown"]:
                    st.markdown(f"- ₹. {d['amount']:.2f}")
                st.markdown(f"**- ₹. {order['discount_amount']:.2f}**")
            else:
                st.markdown(f"**- ₹. {order['discount_amount']:.2f}**")
            st.markdown(f"**₹. {order['total']:.2f}**")

    st.markdown("---")

    
    st.subheader("What's Next?")

   
    if st.button("📥 Download Invoice (PDF)"):
        
        st.info("Generating your invoice... This may take a moment.")
        try:
            pdf_path = orders.generate_invoice(order, f"invoice_{order['order_id']}.pdf")
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="Click to Download",
                    data=f,
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf",
                    key="download_invoice_btn"
                )
        except Exception as e:
            st.error(f"Error generating invoice: {e}")

    
    render_back_to_search()

def main():
    """ Main Application Logic"""
    
    
    
    st.set_page_config(
        page_title = settings.PROJECT_NAME,
        page_icon='🛒',
        initial_sidebar_state = 'expanded'
    )
    
  
    
    initialize_session_state()

    
    
    if 'search_engine' not in st.session_state:
          st.session_state.search_engine = ensure_index_and_load_search_engine()
  
    #Routing based on session state:
    if st.session_state.page =='search':
        
        render_search_page()
    elif st.session_state.page == 'product_detail':
        render_product_detail_page()
    elif st.session_state.page =='cart':
        render_cart_page()
    elif st.session_state.page =='checkout':
        render_checkout_page()
    elif st.session_state.page == 'order_placed':
        render_order_placed_page()
    


if __name__ == "__main__":
    main()
