import json
from channels.generic.websocket import AsyncWebsocketConsumer


# =========================
# 📍 PACKAGE TRACKING SOCKET
# =========================
class TrackingConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.package_id = self.scope['url_route']['kwargs']['package_id']
        self.room_group_name = f"tracking_{self.package_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            print("WS received:", data)
        except:
            pass

    async def send_location(self, event):
        await self.send(text_data=json.dumps({
            "lat": event.get("lat"),
            "lng": event.get("lng"),
            "status": event.get("status")
        }))


# =========================
# 🔔 NOTIFICATION SOCKET
# =========================
class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope["user"]

        if user.is_anonymous:
            await self.close()
            return

        self.group_name = f"user_{user.id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def notify(self, event):
        await self.send(text_data=json.dumps(event["data"]))