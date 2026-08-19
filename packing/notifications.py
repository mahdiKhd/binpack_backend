import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Notification

logger = logging.getLogger(__name__)


def publish_notification(user, event, payload):
    notification = Notification.objects.create(user=user, event=event, payload=payload)
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user.id}",
            {"type": "notification.message", "event": event, "payload": payload},
        )
    except Exception:
        logger.warning(
            "WebSocket delivery failed for notification %s",
            notification.id,
            exc_info=True,
        )
    return notification
