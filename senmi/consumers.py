# consumers.py

import json

from channels.generic.websocket import (
    AsyncWebsocketConsumer
)


# =========================
# 📍 PACKAGE TRACKING SOCKET
# =========================

class TrackingConsumer(
    AsyncWebsocketConsumer
):

    async def connect(self):

        self.package_id = (
            self.scope['url_route']['kwargs']
            ['package_id']
        )

        self.room_group_name = (
            f"tracking_{self.package_id}"
        )

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

        await self.send(
            text_data=json.dumps({
                "lat": event.get("lat"),
                "lng": event.get("lng"),
                "status": event.get("status"),
                "eta_minutes": event.get("eta_minutes"),
            })
        )


# =========================
# 👨‍💼 ADMIN RIDERS SOCKET
# =========================

class AdminRidersConsumer(
    AsyncWebsocketConsumer
):

    async def connect(self):

        self.room_group_name = (
            "admin_riders"
        )

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        print("✅ Admin connected")

    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        print("❌ Admin disconnected")

    async def send_rider_update(
        self,
        event
    ):

        await self.send(
            text_data=json.dumps({
                "type": event.get("type"),
                "message": event.get("message"),
                "rider_id": event.get("rider_id"),
            })
        )


# =========================
# 📊 ADMIN DASHBOARD SOCKET
# =========================

class AdminDashboardConsumer(AsyncWebsocketConsumer):

    async def connect(self):

        self.room_group_name = (
            "admin_dashboard"
        )

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        print("✅ Dashboard connected")

    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        print("❌ Dashboard disconnected")

    async def dashboard_update(
        self,
        event
    ):

        await self.send(
            text_data=json.dumps({
                "type": "refresh"
            })
        )
