def size_options_for(product):
    size_mappnigs = {
        "Topwear": ['XS', 'S', 'M', 'L', 'XL'],
        "Bottomwear": ['28', '30', '32', '34', '36'],
        "Headwear": ['S', 'M', 'L'],
        "Apparel Set": ['XS', 'S', 'M', 'L', 'XL'],
        "Innerwear": ['XS', 'S', 'M', 'L', 'XL'],
        "Dress": ['XS', 'S', 'M', 'L', 'XL'],
        "Gloves": ['S', 'M', 'L'],
        "Loungewear and Sleepwear": ['XS', 'S', 'M', 'L', 'XL'],
        "Footwear": ['6', '7', '8', '9', '10', '11']
    }

    if product["masterCategory"] in ["Apparel", "Accessories"]:
        return size_mappnigs.get(product["subCategory"], ['One Size'])
    elif product["masterCategory"] in ["Footwear"]:
        return size_mappnigs.get("Footwear", ['One Size'])
    elif product["subCategory"] in size_mappnigs:
        return size_mappnigs.get(product["subCategory"])
    else:
        return ['One Size']

def cart_count(cart):
    if len(cart) == 0:
        return 0
    return sum(item['qty'] for item in cart)

def add_to_cart(cart, new_item):
    item_found = False
    for item in cart:
        if item["id"] == new_item["id"] and item["size"] == new_item["size"]:
            item["qty"] += new_item["qty"]
            item_found = True
            break
    if not item_found:
        cart.append(new_item)


def remove_from_cart(cart, idx):
    if 0 <= idx < len(cart):
        del cart[idx]


def cart_total(cart):
    total = sum(item["price"] * item["qty"] for item in cart)
    return round(total, 2)
