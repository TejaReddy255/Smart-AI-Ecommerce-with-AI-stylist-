import google.generativeai as genai
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from config import settings

def format_order_text(order):
    order_summary_parts = [
        f"Order ID: {order['order_id']}",
        f"Date: {order['created_at']}",
        "\nOrder Summary:"
    ]
    for item in order['items']:
        item_line = f"- {item['qty']} x {item['title']} - {item['size']} (₹{item['price']:.2f})"
        order_summary_parts.append(item_line)

    order_summary_parts.append("")
    order_summary_parts.append(f"Subtotal: ₹{order.get('subtotal', 0):.2f}")

    discount_breakdown = order.get('discount_breakdown') or []
    if discount_breakdown:
        order_summary_parts.append("Discont applied:")
        for d in discount_breakdown:
            name = d.get('name', 'Discount')
            amt = d.get('amount', 0)
            order_summary_parts.append(f"- {name}: -₹{float(amt):.2f}")
        order_summary_parts.append(f"Total Discount: -₹{order.get('discount_amount', 0):.2f}")
    else:
        order_summary_parts.append(f"Total Discount: -₹{order.get('discount_amount', 0):.2f}")

    order_summary_parts.append(f"Total: -₹{order.get('total', 0):.2f}")
    order_summary_parts.append("")
    order_summary_parts.append("Shipping Address:")
    order_summary_parts.append(order.get('address', ''))

    order_summary = "\n".join(order_summary_parts)
    return order_summary

def format_order_html(order):
    rows = ""
    for item in order['items']:
        rows +=f"""
        <tr>
            <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{item['qty']}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">{item['title']}</td>
            <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{item['size']}</td>
            <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">{item['price']}</td>
        </tr>
        """
    
    discount_line_html = ""
    discount_breakdown = order.get('discount_breakdown') or []
    if discount_breakdown:
        discount_line_html += "<ul style='margin:6px 0 6px 18px; padding: 0;'>"
        for d in discount_breakdown:
            name = d.get('name', 'Discount')
            amt = d.get('amount', 0)
            discount_line_html += f"<li style='margin-bottom: 4px;'>{name}: -₹{float(amt):.2f}</li>"
        discount_line_html += "</ul>"
        discount_line_html += f"<p style='margin: 6px 0;'><strong>Total Discount:</strong> -₹ {order.get('discount_amount', 0):.2f}</p>"
    else:
        discount_line_html += f"<p style='margin: 6px 0;'><strong>Total Discount:</strong> -₹ {order.get('discount_amount', 0):.2f}</p>"

    html = f"""
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #1f212b">
        <p><strong>Order ID: </strong> {order['order_id']}<br>
        <strong>Date: </strong> {order['created_at']}</p>

        <h3 style="margin-top: 20px; margin-bottom: 8px;">Order Summary:</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 600px; border: 1px solid #ddd">
            <thead>
                <tr style="background-color: #f2f2f2">
                    <th style="border: 1px solid #ddd; padding: 8px; text-align: center">Qty</th>
                    <th style="border: 1px solid #ddd; padding: 8px; text-align: left">Item</th>
                    <th style="border: 1px solid #ddd; padding: 8px; text-align: center">Size</th>
                    <th style="border: 1px solid #ddd; padding: 8px; text-align: right">Price</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>

        <div style='max-width: 700px; margin-top: 12px;'>
            <p style='margin: 8px 0;'><strong>>Subtotal:</strong>₹ {order.get('subtotal', 0):.2f}</p>
            {discount_line_html}
            <p style='margin: 8px 0;'><strong>>Total:</strong>₹ {order.get('total', 0):.2f}</p>
        </div>

        <h3 style="margin-top: 20px; margin-bottom: 8px;">Shipping Address</h3>
        <p>{order.get('address', '')}</p>
    </div>
    """

    return html


def generate_order_email_content(order, returning):
    
    try:
    
        genai.configure(
            api_key = settings.GENAI_API_KEY
        )
        full_prompt = (
            "You are a helpful and friendly AI assistant for a fashion e-commerce store 'StyleScope'. Do not use any other shop name. "
            "Write a warm, professional, and concise order confirmation email. "
            "Do not repeat order details. Only write 2-3 sentences of natural language. "
            "Do not include the subject line or any placeholder for it in email body."
            "All currency amounts are in Indian Rupees (₹). Use the symbol."
            "Do not modify customer name, product name."
            f"Mention the customer by name as {order['customer_name']}. Do not use any other Customer name instead of {order['customer_name']}. "
        )

        if order.get('discount_breakdown'):
            full_prompt += (
                f"This customer recived discounts under various categories. A total discount of Rs.{order['discount_amount']:.2f} was applied to the order. "
                "Thank them for their continued trust in us and mention this special discount. Also mention to refer the discount details in the email. "
            )
        else:
            if returning:
                full_prompt += (
                    f"This is a returning customer. A Loyalty discount of Rs.{order['discount_amount']:.2f} was applied to the order. "
                    "Thank them for their continued loyalty and mention this special discount. "
                )

        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        response = model.generate_content(
            full_prompt
        )
        intro_text = response.text.strip()
        
        # Parsing response to json
        #data = json.loads(response.text.strip().lstrip('````json').rstrip('````'))
        plain_text = intro_text + "\n\n" + format_order_text(order)
        html = f"<p style='font-family: Arial, sans-serif; font-size: 14px; color: #1f212b;'>{intro_text}</p>" + format_order_html(order)


        email_content = {
            "subject": f"StyleScope Order Confirmation: Thank you, {order['customer_name']}!",
            "text": plain_text,
            "html": html
        }
        return email_content, None
    except Exception as e:
        print(f'Error generating email containt with Gemini: {e}')
        fallback_content = "Thank you for your order! We have recieved it and are processing it."
        fallback_email = {
            "subject": f"Order Confirmation for {order['customer_name']}",
            "text": fallback_content + "\n\n" + format_order_text(order),
            "html": f"<p style='font-family: Arial, sans-serif; font-size: 14px; color: #1f212b;'>{fallback_content}</p>" + format_order_html(order)
        }
        return fallback_email, e
