-- Match the whitespace stripped by the Python API, including tabs and Unicode spaces.
-- Keep existing resolutions immutable; invalid legacy rows must fail validation.
alter table agents_factory_private.whatsapp_account_update_alert_resolutions
  add constraint whatsapp_alert_resolution_note_trimmed check (
    resolution_note = btrim(
      resolution_note,
      U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
    )
  );
