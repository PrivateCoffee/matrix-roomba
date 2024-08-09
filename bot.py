import nio
import asyncio
import aiohttp
import yaml
import logging


class RoombaBot:
    def __init__(
        self,
        homeserver,
        user_id,
        access_token,
        moderation_room_id,
        pantalaimon_homeserver=None,
        pantalaimon_token=None,
        shutdown_title=None,
        shutdown_message=None,
    ):
        """Initialize the bot.

        Args:
            homeserver (str): The homeserver URL.
            user_id (str): The user ID of the bot.
            access_token (str): The access token of the bot.
            moderation_room_id (str): The room ID of the moderation room.
            pantalaimon_homeserver (str, optional): The homeserver URL of the Pantalaimon instance. Defaults to None, which means no Pantalaimon.
            pantalaimon_token (str, optional): The access token of the Pantalaimon instance. Defaults to None. Required if pantalaimon_homeserver is set.
            shutdown_title (str, optional): The title of the shutdown message. Defaults to None.
            shutdown_message (str, optional): The message of the shutdown message. Defaults to None.
        """
        self.homeserver = homeserver
        self.access_token = access_token

        self.shutdown_title = shutdown_title or "Content Violation Notification"
        self.shutdown_message = shutdown_message or (
            "A room you were a member of has been shutdown on this server due to content violations. Please review our Terms of Service."
        )

        if pantalaimon_homeserver and pantalaimon_token:
            self.client = nio.AsyncClient(pantalaimon_homeserver)
            self.client.access_token = pantalaimon_token

        else:
            self.client = nio.AsyncClient(homeserver)
            self.client.access_token = access_token

        self.client.user_id = user_id

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
        elif event.body.startswith("!roomba shutdown"):
            parts = event.body.split()

            if "--purge" in parts:
                parts.remove("--purge")
                purge = True
            else:
                purge = False

            room_id = parts[2]
            await self.shutdown_room(room_id, purge)
        elif event.body.startswith("!roomba "):
            await self.send_message(
                self.moderation_room_id,
                "Unknown command. Use '!roomba block <room_id>', '!roomba unblock <room_id>', or '!roomba shutdown <room_id> [--purge]'.",
            )

    async def block_room(self, room_id, block):
        """Block or unblock a room.

        Args:
            room_id (str): The room ID to block or unblock.
            block (bool): Whether to block or unblock the room.
        """
        url = f"{self.homeserver}/_synapse/admin/v1/rooms/{room_id}/block"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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
                    local_users = await self.get_local_users(room_id)
                    await self.send_message(
                        self.moderation_room_id,
                        f"Room {room_id} {'blocked' if block else 'unblocked'} successfully. Local users: {', '.join(local_users)}",
                    )
                else:
                    self.logger.error(
                        f"Failed to {'block' if block else 'unblock'} room {room_id}: {resp.status}"
                    )
                    await self.send_message(
                        self.moderation_room_id,
                        f"Failed to {'block' if block else 'unblock'} room {room_id}.",
                    )

    async def get_local_users(self, room_id):
        """Get the local users in a room.

        Args:
            room_id (str): The room ID to get the local users from.

        Returns:
            list: The list of local users in the room.
        """
        members_url = f"{self.homeserver}/_matrix/client/r0/rooms/{room_id}/members"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        local_users = []

        async with aiohttp.ClientSession() as session:
            async with session.get(members_url, headers=headers) as resp:
                if resp.status == 200:
                    members = await resp.json()
                    for member in members.get("chunk", []):
                        user_id = member.get("user_id")
                        if user_id and user_id.endswith(
                            self.client.user_id.split(":")[1]
                        ):
                            local_users.append(user_id)
        return local_users

    async def shutdown_room(self, room_id, purge=True):
        """Shutdown and optionally purge a room.

        Args:
            room_id (str): The room ID to shut down.
            purge (bool, optional): Whether to purge the room. Defaults to True.
        """
        url = f"{self.homeserver}/_synapse/admin/v2/rooms/{room_id}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "new_room_user_id": self.client.user_id,
            "room_name": self.shutdown_title,
            "message": self.shutdown_message,
            "block": True,
            "purge": purge,
        }

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers, json=body) as resp:
                if resp.status == 200:
                    response = await resp.json()
                    delete_id = response.get("delete_id")
                    self.logger.debug(
                        f"Room {room_id} shutdown initiated successfully: delete_id={delete_id}"
                    )
                    local_users = await self.get_local_users(room_id)
                    await self.send_message(
                        self.moderation_room_id,
                        f"Room {room_id} shutdown initiated successfully. Delete ID: {delete_id}. Local users: {', '.join(local_users)}",
                    )
                else:
                    self.logger.error(
                        f"Failed to shutdown room {room_id}: {resp.status}"
                    )
                    await self.send_message(
                        self.moderation_room_id,
                        f"Failed to shutdown room {room_id}.",
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

    if "pantalaimon" in config:
        pantalaimon_homeserver = config["pantalaimon"]["homeserver"]
        pantalaimon_token = config["pantalaimon"]["access_token"]
    else:
        pantalaimon_homeserver = None
        pantalaimon_token = None

    if "shutdown" in config:
        shutdown_title = config["shutdown"].get("title")
        shutdown_message = config["shutdown"].get("message")
    else:
        shutdown_title = None
        shutdown_message = None

    # Create and start the bot
    bot = RoombaBot(
        homeserver,
        user_id,
        access_token,
        moderation_room_id,
        pantalaimon_homeserver,
        pantalaimon_token,
        shutdown_title,
        shutdown_message,
    )
    await bot.start()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
