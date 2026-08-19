# from sqlmodel import Session, SQLModel, create_engine
# from neurocom_backend.database.models.user import Customer
# from neurocom_backend.database.models.product import Product
# from neurocom_backend.database.models.order import Order, OrderStatus, ProductOrder
# from neurocom_backend.database.connection import get_session, engine
# from uuid import uuid4
# from datetime import datetime
# from fastapi import Depends
# import random
# from typing import Annotated
# from neurocom_backend.services.order_service import store_new_order
# from neurocom_backend.services.product_service import store_new_product
# from neurocom_backend.services.user_service import store_new_user
# from neurocom_backend.utils.security import hash_password
# import requests

# customers = [
#     Customer(full_name="Alice Johnson", email="alice@example.com", password="alice123", address="123 Apple St", phone_number="1234567890"),
#     Customer(full_name="Bob Smith", email="bob@example.com", password="bob123", address="456 Orange Ave", phone_number="9876543210"),
#     Customer(full_name="Charlie Brown", email="charlie@example.com", password="charlie123", address="789 Banana Blvd", phone_number="5551112222"),
#     Customer(full_name="Diana Prince", email="diana@example.com", password="diana123", address="101 Peach St", phone_number="5553334444"),
#     Customer(full_name="Ethan Hunt", email="ethan@example.com", password="ethan123", address="202 Pear Dr", phone_number="5555556666"),
#     Customer(full_name="Fiona Gallagher", email="fiona@example.com", password="fiona123", address="303 Cherry Cir", phone_number="5557778888"),
#     Customer(full_name="George Miller", email="george@example.com", password="george123", address="404 Mango Ave", phone_number="5559990000"),
#     Customer(full_name="Hannah Baker", email="hannah@example.com", password="hannah123", address="505 Coconut Ln", phone_number="1112223333"),
#     Customer(full_name="Ian Malcolm", email="ian@example.com", password="ian123", address="606 Papaya Rd", phone_number="4445556666"),
#     Customer(full_name="Julia Roberts", email="julia@example.com", password="julia123", address="707 Grape Ct", phone_number="7778889999"),
#     Customer(full_name="Kevin Hart", email="kevin@example.com", password="kevin123", address="808 Melon Pl", phone_number="2223334444"),
#     Customer(full_name="Laura Palmer", email="laura@example.com", password="laura123", address="909 Plum Way", phone_number="3334445555"),
#     Customer(full_name="Michael Scott", email="michael@example.com", password="michael123", address="111 Kiwi Dr", phone_number="8889990000"),
#     Customer(full_name="Nina Dobrev", email="nina@example.com", password="nina123", address="222 Lemon Blvd", phone_number="6667778888"),
#     Customer(full_name="Oscar Isaac", email="oscar@example.com", password="oscar123", address="333 Lime St", phone_number="9990001111"),
# ]


# def seed_db_with_mock_data():
#     try:
#         with Session(engine) as db:
#             print("Seeding started...")
#             products: list[Product] = []
#             for i in range(1,15):
#                 res = requests.get(f"https://fakestoreapi.com/products/{i}")
#                 product_data = res.json()
#                 product = Product(
#                     title=product_data["title"],
#                     category=product_data["category"],
#                     description=product_data["description"],
#                     price=product_data["price"],
#                     image=product_data["image"]
#                 )
#                 products.append(product)
#             db.add_all(products)
#             db.commit()
#             print("Added products.")
            
#             # Update customers with hashed passwords
#             for cust in customers:
#                 cust.password = hash_password(cust.password)
#             db.add_all(customers)
#             db.commit()
#             print("Added customers.")
            
#             for cust in customers:
#                 order = Order(
#                     customer_id=cust.id,
#                     status=random.choice(list(OrderStatus)),
#                     total_amount=0  # will be updated
#                 )
#                 db.add(order)
#                 db.commit()
#                 order_total = 0

#                 for product in random.sample(products, k=2):
#                     qty = random.randint(1, 3)
#                     subtotal = product.price * qty
#                     order_total += subtotal
#                     po = ProductOrder(
#                         product_id=product.id,
#                         order_id=order.id,
#                         quantity=qty,
#                         sub_total=subtotal
#                     )
#                     db.add(po)
#                     db.commit()
#                     print("Added product order.")
#                 order.total_amount = order_total
#                 db.add(order)
#                 db.commit()
#                 print("Updated order.")
#             print("Seeding completed.")
#     except Exception as e:
#         print(f"Seeding failed with error: {e}")