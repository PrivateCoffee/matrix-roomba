import nio
import asyncio
import aiohttp
import yaml
import logging


class RoombaBot:
    def __init__(self, homeserver, user_id, access_token, moderation_room_id):
        """Initialize the bot.

        Args:
            homeserver (str): The homeserver URL.
            user_id (str): The user ID of the bot.
            access_token (str): The access token of the bot.
            moderation_room_id (str): The room ID of the moderation room.
        """
        self.client = nio.AsyncClient(homeserver, user_id)
        self.client.access_token = access_token
        self.moderation_room_id = moderation_room_id
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

        self.logger.addHandler(handler)

    async def start(self):
        """Start the bot."""
        self.client.add_event_callback(self.message_callback, nio.RoomMessageText)
        await self.client.sync_forever(timeout=30000)

    async def message_callback(self, room, event):
        """Callback for when a message is received in a room.

        Args:
            room (nio.room.Room): The room the message was received in.
            event (nio.events.room_events.RoomMessageText): The message event.
        """
        if room.room_id != self.moderation_room_id:
            return

        if event.body.startswith("!roomba block"):
            await self.block_room(event.body.split()[2], True)
        elif event.body.startswith("!roomba unblock"):
            await self.block_room(event.body.split()[2], False)

    async def block_room(self, room_id, block):
        """Block or unblock a room.

        Args:
            room_id (str): The room ID to block or unblock.
            block (bool): Whether to block or unblock the room.
        """
        url = f"{self.client.homeserver}/_synapse/admin/v1/rooms/{room_id}/block"
        headers = {
            "Authorization": f"Bearer {self.client.access_token}",
            "Content-Type": "application/json",
        }
        body = {"block": block}

        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=body) as resp:
                if resp.status == 200:
                    response = await resp.json()
                    self.logger.debug(
                        f"Room {room_id} {'blocked' if block else 'unblocked'} successfully: {response}"
                    )
                    await self.send_message(
                        self.moderation_room_id,
                        f"Room {room_id} {'blocked' if block else 'unblocked'} successfully.",
                    )
                else:
                    self.logger.error(
                        f"Failed to {'block' if block else 'unblock'} room {room_id}: {resp.status}"
                    )
                    await self.send_message(
                        self.moderation_room_id,
                        f"Failed to {'block' if block else 'unblock'} room {room_id}.",
                    )

    async def send_message(self, room_id, message):
        """Send a message to a room.

        Args:
            room_id (str): The room ID to send the message to.
            message (str): The message to send.
        """
        content = {"msgtype": "m.text", "body": message}
        self.logger.debug(f"Sending message to {room_id}: {message}")
        await self.client.room_send(
            room_id, message_type="m.room.message", content=content
        )


async def main():
    # Load configuration from config.yaml
    with open("config.yaml", "r") as config_file:
        config = yaml.safe_load(config_file)

    homeserver = config["homeserver"]
    user_id = config["user_id"]
    access_token = config["access_token"]
    moderation_room_id = config["moderation_room_id"]

    # Create and start the bot
    bot = RoombaBot(homeserver, user_id, access_token, moderation_room_id)
    await bot.start()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
