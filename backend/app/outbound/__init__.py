"""Real outbound for Sourced and any other AI employee: find a candidate's email, send it through Send Guard,
track delivery and replies. See docs/OUTBOUND.md.

    contacts.find_emails(client, profile_urls)      live Crustdata Person Enrich, fields ["contact"]
    send.guarded_send(agent_id, to, subject, body)   Send Guard, then a real provider (Resend or SMTP/Gmail)
    messages                                         the sent-message store (status, events, replies)
    tracking.refresh()                               delivery status from the provider + replies over IMAP
"""
