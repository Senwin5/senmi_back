import json
from channels.generic.websocket import AsyncWebsocketConsumer

class TrackingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.package_id = self.scope['url_route']['kwargs']['package_id']
        self.room_group_name = f"tracking_{self.package_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def send_location(self, event):
        await self.send(text_data=json.dumps({
            'lat': event['lat'],
            'lng': event['lng'],
            'status': event.get('status')
        }))

  


