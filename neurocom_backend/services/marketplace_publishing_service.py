from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlmodel import Session, select

from neurocom_backend.database.models.marketplace import ConnectedStorePublishResult, Marketplace, MarketplaceConnection, PublishConnectedProductRequest, PublishConnectedProductResponse
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.models.shopify_model import ShopifyProductCreate
from neurocom_backend.services.daraz_service import create_new_product as create_daraz_product
from neurocom_backend.services.marketplace_service import is_daraz_marketplace, is_shopify_marketplace
from neurocom_backend.services.shopify_service import create_new_product as create_shopify_product, decode_shopify_credentials
from neurocom_backend.utils.security import decrypt_value



def _error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)
    return str(error) or error.__class__.__name__


def publish_to_connected_stores(payload: PublishConnectedProductRequest, db: Session, merchant: Merchant) -> PublishConnectedProductResponse:
    connections = db.exec(select(MarketplaceConnection).join(Marketplace).where(MarketplaceConnection.merchant_id == merchant.id)).all()
    results: list[ConnectedStorePublishResult] = []
    for connection in connections:
        marketplace = connection.marketplace
        if marketplace is None:
            continue
        base = {"connection_id": connection.id, "marketplace_id": connection.marketplace_id, "marketplace": marketplace.slug, "store_identifier": connection.store_identifier}
        if not connection.encrypted_access_token:
            results.append(ConnectedStorePublishResult(**base, success=False, error="No active credentials for this connection"))
        try:
            if is_shopify_marketplace(marketplace):
                if payload.shopify is None: continue
                product = ShopifyProductCreate.model_validate(payload.shopify)
                shop, access_token = decode_shopify_credentials(decrypt_value(connection.encrypted_access_token))
                result = create_shopify_product(shop, access_token, product)
            elif is_daraz_marketplace(marketplace):
                if payload.daraz is None: continue
                result = create_daraz_product(decrypt_value(connection.encrypted_access_token), payload.daraz)
                if not isinstance(result, dict) or str(result.get("code", "")) != "0":
                    raise ValueError((result or {}).get("message", "Daraz did not create the product"))
            else:
                raise ValueError("Publishing is not supported for this marketplace")
            results.append(ConnectedStorePublishResult(**base, success=True, result=result))
        except (InvalidToken, ValueError, TypeError, KeyError, HTTPException) as error:
            results.append(ConnectedStorePublishResult(**base, success=False, error=_error_message(error)))
        except Exception as error:
            results.append(ConnectedStorePublishResult(**base, success=False, error="Unexpected publishing error: " + _error_message(error)))
    succeeded = sum(result.success for result in results)
    return PublishConnectedProductResponse(results=results, succeeded=succeeded, failed=len(results) - succeeded)
