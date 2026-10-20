"""Shared display projection for authenticated readers. `c` is a conversation."""

CONTACT_COLUMNS = """
coalesce(p.profile_name,nullif(btrim(book.full_name),''),nullif(btrim(book.first_name),'')) AS contact_name,
p.username AS contact_username,
coalesce(p.phone_number,CASE WHEN book.customer_wa_id ~ '^[1-9][0-9]{6,14}$'
 THEN '+' || book.customer_wa_id END) AS contact_phone_number
"""

CONTACT_JOINS = """
LEFT JOIN public.whatsapp_contact_profiles p
 ON (p.tenant_id,p.whatsapp_account_id,p.customer_wa_id) =
    (c.tenant_id,c.whatsapp_account_id,c.customer_wa_id)
LEFT JOIN public.whatsapp_contacts book
 ON (book.tenant_id,book.whatsapp_account_id,book.customer_wa_id) =
    (c.tenant_id,c.whatsapp_account_id,c.customer_wa_id) AND NOT book.is_deleted
"""
