from neurocom_backend.python.lazop.base import LazopClient, LazopRequest
import os
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
import json
from neurocom_backend.models.daraz_model import DarazProductCreate
from typing import Any
from datetime import datetime, timedelta
import concurrent.futures

_:bool = load_dotenv()

lazop_client = LazopClient("https://api.daraz.pk/rest", os.getenv("DARAZ_APP_KEY"), os.getenv("DARAZ_APP_SECRET"))

def get_auth_code():
    pass

def get_access_token(code: str):
    access_token_request = LazopRequest("/auth/token/create")
    access_token_request.add_api_param("code", code)
    access_token_response = lazop_client.execute(access_token_request)
    print("Auth access token: ", access_token_response.body)
    access_token = access_token_response.body["access_token"]
    return access_token

def get_all_products(access_token: str):
    print("access_token: ", access_token)
    all_products_request = LazopRequest("/products/get",'GET')
    all_products_request.add_api_param("offset", "0")
    all_products_request.add_api_param("limit", "50")
    all_products_request.add_api_param('filter', 'live')
    all_products_response = lazop_client.execute(all_products_request, access_token)
    print("Products: ", all_products_response.body)
    return all_products_response.body
    
def get_all_products_reviews(access_token: str):
    all_products = get_all_products(access_token)

    if isinstance(all_products, str):
        all_products = json.loads(all_products)

    product_list = all_products.get("data", {}).get("products", [])
    print(f"Fetching reviews for {len(product_list)} products: ")
    all_reviews = []

    def fetch_reviews(product):
        item_id = product.get("item_id")
        if not item_id:
            return None
        try:
             reviews = get_product_reviews(item_id, access_token)
             return {
                "product": product,
                "reviews": reviews
            }
        except Exception as e:
            print(f"Error fetching reviews for item {item_id}: {e}")
            return {
                "product": product,
                "reviews": []
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_reviews, p) for p in product_list]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                all_reviews.append(result)
    return [review for review in all_reviews if review["reviews"]]

def get_time_range(days=7):
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)

    return (
        int(start_time.timestamp() * 1000),
        int(end_time.timestamp() * 1000)
    )
    
def get_product_reviews(product_id: str, access_token: str):
    start_time, end_time = get_time_range(days=7)
    product_reviews_request = LazopRequest("/review/seller/history/list",'GET')
    product_reviews_request.add_api_param('item_id', product_id)
    product_reviews_request.add_api_param('start_time', start_time)
    product_reviews_request.add_api_param('end_time', end_time)
    product_reviews_request.add_api_param('current', '1')
    product_reviews_response = lazop_client.execute(product_reviews_request, access_token)
    data = product_reviews_response.body["data"]
    print("Product reviews history data: ", data)
    id_list = data.get("id_list", None)
    if id_list is None:
      print("No reviews found")
      return []
    print("ID LIST: ", id_list)
    reviews_request = LazopRequest('/review/seller/list/v2','GET')
    reviews_request.add_api_param('id_list', json.dumps(id_list))
    reviews_response = lazop_client.execute(reviews_request, access_token)
    print("Reviews response: ",reviews_response.body)
    return reviews_response.body["data"]["review_list"]
  
def get_category_attributes(category_id: str):
    request = LazopRequest("/category/attributes/get", "GET")
    request.add_api_param("primary_category_id", category_id)
    response = lazop_client.execute(request)
    return response.body
  
from functools import lru_cache

@lru_cache(maxsize=1)
def get_all_categories():
    request = LazopRequest("/category/tree/get", "GET")
    response = lazop_client.execute(request)
    return response.body["data"]

def find_category(categories, category_id: int):
    for category in categories:
        if int(category["category_id"]) == category_id:
            return category
        if "children" in category and category["children"]:
            result = find_category(category["children"], category_id)
            if result:
                return result
    return None

def get_category_by_id(category_id: int):
    all_categories = get_all_categories()
    return find_category(all_categories, category_id)
      
def get_category_children(category_id: int):
    all_categories_request = LazopRequest("/category/tree/get", "GET")
    response = lazop_client.execute(all_categories_request)

    all_categories_tree = response.body
    if isinstance(all_categories_tree, str):
        all_categories_tree = json.loads(all_categories_tree)

    categories = all_categories_tree.get("data", [])

    def find_category(categories, category_id):
        for category in categories:
            # FIX: Daraz uses "category_id", not "id"
            if int(category["category_id"]) == category_id:
                return category.get("children", [])
            children = category.get("children", [])
            if children:
                found = find_category(children, category_id)
                if found is not None:
                    return found
        return None

    return find_category(categories, category_id) or []

def migrate_image(access_token: str, image_url: str):
  print(access_token)
  request = LazopRequest('/image/migrate')
  xml_payload = f"""
<Request>
    <Image>
        <Url>{image_url}</Url>
    </Image>
</Request>
  """
  request.add_api_param("payload", xml_payload)
  response = lazop_client.execute(request, access_token)
  print(response)
  if isinstance(response.body, dict):
        return response.body
  else:
    return json.loads(response.body)
  
def migrate_images(access_token: str, images_urls: list[str]):
  
  image_urls = [
    "https://fakestoreapi.com/img/71li-ujtlUL._AC_UX679_t.png",
    "https://fakestoreapi.com/img/71YXzeOuslL._AC_UY879_t.png"
    ]
  request = LazopRequest('/images/migrate')
  
  xml_payload = """
  <?xml version="1.0" encoding="UTF-8" ?>
<Request>
    <Images>
        <Url>https://fakestoreapi.com/img/71li-ujtlUL._AC_UX679_t.png</Url>
        <Url>https://fakestoreapi.com/img/71YXzeOuslL._AC_UY879_t.png</Url>
    </Images>
</Request>
  """
  request.add_api_param("payload", xml_payload)
  response = lazop_client.execute(request, access_token)
  print(response)
  if isinstance(response.body, dict):
        return response.body
  else:
    return json.loads(response.body)
  
def get_migrated_images(access_token: str, batch_id: str):
    request = LazopRequest('/image/response/get', 'GET')
    request.add_api_param('batch_id', batch_id)
    response = lazop_client.execute(request, access_token)
    print(response)
    if isinstance(response.body, dict):
        return response.body
    return json.loads(response.body)
  
def create_new_product(access_token: str, product: Any):
  print(product)
  create_product_request = LazopRequest('/product/create')
  attributes_xml = "".join([
        f"<{attr_name}>{attr_value}</{attr_name}>" for attr_name, attr_value in product["Attributes"].items() if attr_value is not None and attr_value != ""
  ])
  images_xml = "".join([f"<Image>{img}</Image>" for img in product["Images"]])
  skus_xml = ""
  for sku in product["Skus"]:
    sku_images_xml = "".join([f"<Image>{img}</Image>" for img in sku.get("Images", [])])
    skus_xml += f"""
        <Sku>
            <SellerSku>{sku['SellerSku']}</SellerSku>
            <color_family>{sku.get("color_family", "")}</color_family>
            <size>{sku.get("size", "")}</size>
            <quantity>{sku['quantity']}</quantity>
            <price>{sku['price']}</price>
            <package_length>{sku['package_length']}</package_length>
            <package_height>{sku['package_height']}</package_height>
            <package_weight>{sku['package_weight']}</package_weight>
            <package_width>{sku['package_width']}</package_width>
            <package_content>{sku['package_content']}</package_content>
            <Images>{sku_images_xml}</Images>
        </Sku>
        """
  xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Request>
      <Product>
        <PrimaryCategory>{product["PrimaryCategory"]}</PrimaryCategory>
        <SPUId/>
        <AssociatedSku/>
        <Images>{images_xml}</Images>
        <Attributes>{attributes_xml}</Attributes>
        <Skus>{skus_xml}</Skus>
      </Product>
    </Request>"""
    
  print("Final XML Payload: ", xml_payload)
  create_product_request.add_api_param('payload', xml_payload)
  response = lazop_client.execute(create_product_request, access_token)
  return JSONResponse({"type": response.type, "body": response.body})
  
    #  <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
    #           <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
    # <brand>Remark</brand>
              
# def create_new_product(access_token: str, product: DarazProductCreate):
#     create_product_request = LazopRequest('/product/create')
#     xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Request>
#           <Product>
#             <PrimaryCategory>{product.PrimaryCategory}</PrimaryCategory>
#             <SPUId/>
#             <AssociatedSku/>
#             <Images>
#               {''.join([f'<Image>{img}</Image>' for img in product.Images])}
#             </Images>
#             <Attributes>
#               <name>{product.name}</name>
#               <short_description>{product.short_description}</short_description>
#               <short_description_en>{product.short_description}</short_description_en>
#               <description>{product.description}</description>
#               <description_en>{product.description}</description_en>
#               <brand>{product.brand}</brand>
#               <model>asdf</model>
#               <kid_years>Kids (6-10yrs)</kid_years>
#               <name_en>{product.name}</name_en>
#               <occasion>Casual</occasion>
#               <age_range>Standard</age_range>
#               <warranty_type>No Warranty</warranty_type>
#             </Attributes>
#             <Skus>
#               <Sku>
#                 <SellerSku>api-create-test-2</SellerSku>
#                 <color_family>Green</color_family>
#                 <size>40</size>
#                 <quantity>1</quantity>
#                 <price>389</price>
#                 <package_length>11</package_length>
#                 <package_height>22</package_height>
#                 <package_weight>33</package_weight>
#                 <package_width>44</package_width>
#                 <package_content>this is what's in the box</package_content>
#                 <Images>
#                   <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
#                   <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
#                 </Images>
#               </Sku>
#             </Skus>
#           </Product>
#         </Request>"""
        
#     create_product_request.add_api_param('payload', xml_payload)
#     response = lazop_client.execute(create_product_request, access_token)
#     return JSONResponse({"type": response.type, "body": response.body})


def get_all_orders(access_token: str):
    all_orders_request = LazopRequest("/orders/get",'GET')
    all_orders_request.add_api_param("offset", "0")
    all_orders_request.add_api_param("limit", "10")
    all_orders_request.add_api_param("sort_by", "updated_at")
    all_orders_request.add_api_param('sort_direction', 'DESC')
    all_orders_request.add_api_param('created_after', '2017-02-10T09:00:00+08:00')
    all_orders_response = lazop_client.execute(all_orders_request, access_token)
    print("Orders: ", all_orders_response.body)
    return all_orders_response.body["data"]["orders"]

def get_order_detail(order_id: str, access_token: str):
    order_detail_request = LazopRequest('/order/items/get','GET')
    order_detail_request.add_api_param('order_id', order_id)
    order_detail_response = lazop_client.execute(order_detail_request, access_token)
    print("Order detail: ", order_detail_response.body)
    return order_detail_response.body
  
def get_orders_details(order_ids: list[str], access_token: str):
  print("Order IDs: ", order_ids)
  orders_details_request = LazopRequest('/orders/items/get','GET')
  orders_details_request.add_api_param('order_ids', f"{order_ids}")
  orders_details_response = lazop_client.execute(orders_details_request, access_token)
  print("Orders details: ", orders_details_response.body)
  return orders_details_response.body["data"]
  
def get_orders_with_items(access_token: str):
    orders = get_all_orders(access_token)
    if(not orders):
      return []
    print("Orders: ", orders[0]["order_id"], type(orders[0]["order_id"]))
    order_ids = [int(o["order_id"]) for o in orders]
    print(order_ids)

    details = get_orders_details(order_ids, access_token)

    merged_orders = []
    for order in orders:
        order_id = order["order_id"]
        order_items = next(
            (d["order_items"] for d in details if d["order_id"] == order_id),
            []
        )
        merged_orders.append({
            **order,
            "items": order_items
        })

    return merged_orders
  
# def get_order_logistic_details(order_id: str, access_token: str):
#   order_logistic_request = LazopRequest('/order/logistic/get')
#   order_logistic_request.add_api_param('order_id', order_id)
#   order_logistic_request.add_api_param('package_id_list', '[]')
#   order_logistic_request.add_api_param('locale', 'en')
#   order_logistic_response = lazop_client.execute(order_logistic_request, access_token)
#   print("Order Logistic Details: ", order_logistic_response.body)
#   order_tracking_number = order_logistic_response.body["data"]["module"][0]["package_detail_info_list"][0].get("tracking_number", None)
#   if(order_tracking_number is None):
#     print("No tracking number found")
#     return {}
#   order_package_history_request = LazopRequest("/logistics/epis/packages/history",'GET')
#   order_package_history_request.add_api_param('includeTimeline', 'true')
#   order_package_history_request.add_api_param('trackingNumber', order_tracking_number)
#   order_package_history_response = lazop_client.execute(order_package_history_request)
#   print("Package history details: ", order_package_history_response.body)
#   return order_package_history_response.body

def get_order_logistic_details(order_id: str, access_token: str):
    # Step 1: Fetch logistic details
    order_logistic_request = LazopRequest('/order/logistic/get')
    order_logistic_request.add_api_param('order_id', order_id)
    order_logistic_request.add_api_param('package_id_list', '[]')
    order_logistic_request.add_api_param('locale', 'en')

    order_logistic_response = lazop_client.execute(order_logistic_request, access_token)
    print("Order Logistic Details: ", order_logistic_response.body)

    try:
        # body = json.loads(order_logistic_response.body)
        modules = order_logistic_response.body.get("data", {}).get("module", [])
        print("Modules: ", modules)
        if not modules:
            print("No modules found in logistic details")
            return {}

        package_list = modules[0].get("packageDetailInfoList", [])
        if not package_list:
            print("No package details found")
            return {}

        order_tracking_number = package_list[0].get("trackingNumber")
        print("Tracking Number: ", order_tracking_number)
        if not order_tracking_number:
            print("No tracking number found")
            return {}

    except Exception as e:
        print("Error parsing logistic response:", e)
        return {}

    # Step 2: Fetch package history
    order_package_history_request = LazopRequest("/logistics/epis/packages/history", 'GET')
    order_package_history_request.add_api_param('includeTimeline', 'true')
    order_package_history_request.add_api_param('trackingNumber', order_tracking_number)

    order_package_history_response = lazop_client.execute(order_package_history_request, access_token)
    print("Package history details: ", order_package_history_response.body)

    # Return parsed JSON instead of raw string (optional)
    try:
        return json.loads(order_package_history_response.body)
    except:
        return {"raw": order_package_history_response.body}

def trace_order_by_id(order_id: str, access_token: str):
    trace_order_request = LazopRequest("/logistic/order/trace",'GET')
    # trace_order_request = LazopRequest("/logistics/epis/packages/history",'GET')
    trace_order_request.add_api_param("order_id", order_id)
    trace_order_request.add_api_param('locale', 'en')
    trace_order_request.add_api_param('ofcPackageIdList', '[]')
    track_order_response = lazop_client.execute(trace_order_request, access_token)
    print("Track Order Data: ", track_order_response.body)
    return track_order_response.body

def get_reverse_orders(access_token: str):
    reverse_orders_request = LazopRequest("/reverse/getreverseordersforseller",'GET')
    reverse_orders_request.add_api_param('page_no', '1')
    reverse_orders_request.add_api_param('page_size', '10')
    reverse_orders_response = lazop_client.execute(reverse_orders_request, access_token)
    print("Reverse orders: ", reverse_orders_response.body)
    return reverse_orders_response.body["result"]["items"]

def get_reverse_order_info(reverse_order_id: str, access_token: str):
    reverse_order_request = LazopRequest("/order/reverse/return/detail/list",'GET')
    reverse_order_request.add_api_param('reverse_order_id', reverse_order_id)
    reverse_order_response = lazop_client.execute(reverse_order_request, access_token)
    print("Reverse orders info: ", reverse_order_response.body)
    return reverse_order_response.body

def get_all_reverse_orders_info(access_token: str):
  reverse_orders = get_reverse_orders(access_token)
  print("reverse orders: ", reverse_orders)
  reverse_orders_info = []
  for reverse_order in reverse_orders:
    print(reverse_order)
    info = get_reverse_order_info(reverse_order['reverse_order_id'], access_token)
    print(info)
    reverse_orders_info.append(info)
  print("reverse orders info: ",reverse_orders_info )
  return reverse_orders_info

def payout_statement(access_token: str):
  request = LazopRequest('/finance/payout/status/get','GET')
  request.add_api_param('created_after', '2018-01-01')
  response = lazop_client.execute(request, access_token)
  print(response.type)
  print(response.body)
  return response.body