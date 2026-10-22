"""Export visible full conversation history, including compacted messages."""
def export_history(store, session_id):
    with store.transaction():
        page = store.conversation_history(session_id, 200)
        if page['total'] > 10000:
            raise ValueError('Export is limited to 10000 messages; use paginated history')
        items = list(page['messages'])
        size = sum(len(item['content'].encode('utf-8')) for item in items)
        while page['has_more']:
            page = store.conversation_history(session_id, 200, page['next_before_id'])
            size += sum(len(item['content'].encode('utf-8')) for item in page['messages'])
            if size > 16 * 1024 * 1024:
                raise ValueError('Export is limited to 16 MiB; use paginated history')
            items = page['messages'] + items
        if size > 16 * 1024 * 1024:
            raise ValueError('Export is limited to 16 MiB; use paginated history')
        return dict(schema='clawos.conversation-export.v1',session_id=session_id,
                    count=len(items),messages=items)
