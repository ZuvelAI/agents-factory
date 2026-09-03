from agents_factory.modules.integrations.contracts import ConnectorManifest
from agents_factory.modules.integrations.orders import OPERATIONS


WOOCOMMERCE_MANIFEST = ConnectorManifest(
    stable_name="woocommerce",
    display_name="WooCommerce",
    version="1.0.0",
    availability="AVAILABLE",
    supported_operations=OPERATIONS,
    executable_entry_point="agents_factory.modules.integrations.woocommerce.client.WooCommerceConnector",
    availability_note="Native order operations; exact store, credentials and per-binding write permissions required. Cancellation is request-only.",
)
