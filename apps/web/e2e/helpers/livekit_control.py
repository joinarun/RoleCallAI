"""Small local-only LiveKit control helper for Playwright acceptance tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from livekit import api


def client() -> api.LiveKitAPI:
    url = os.environ.get("LIVEKIT_URL", "http://127.0.0.1:7880")
    return api.LiveKitAPI(
        url.replace("ws://", "http://").replace("wss://", "https://"),
        os.environ.get("LIVEKIT_API_KEY", "replace-with-local-livekit-api-key"),
        os.environ.get(
            "LIVEKIT_API_SECRET",
            "replace-with-local-livekit-secret-at-least-32-bytes",
        ),
    )


async def run(args: argparse.Namespace) -> None:
    livekit = client()
    try:
        if args.action == "participants":
            response = await livekit.room.list_participants(
                api.ListParticipantsRequest(room=args.room)
            )
            print(
                json.dumps(
                    [
                        {
                            "identity": item.identity,
                            "tracks": len(item.tracks),
                            "canPublish": item.permission.can_publish,
                        }
                        for item in response.participants
                    ]
                )
            )
        elif args.action == "permission":
            await livekit.room.update_participant(
                api.UpdateParticipantRequest(
                    room=args.room,
                    identity=args.identity,
                    permission=api.ParticipantPermission(
                        can_subscribe=True,
                        can_publish=args.can_publish,
                        can_publish_data=True,
                    ),
                )
            )
            print(json.dumps({"ok": True}))
        elif args.action == "send":
            await livekit.room.send_data(
                api.SendDataRequest(
                    room=args.room,
                    data=args.message.encode(),
                    kind=api.DataPacketKind.RELIABLE,
                    topic="rolecall.v1",
                )
            )
            print(json.dumps({"ok": True}))
        elif args.action == "delete":
            await livekit.room.delete_room(api.DeleteRoomRequest(room=args.room))
            print(json.dumps({"ok": True}))
    finally:
        await livekit.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    participants = subparsers.add_parser("participants")
    participants.add_argument("room")
    permission = subparsers.add_parser("permission")
    permission.add_argument("room")
    permission.add_argument("identity")
    permission.add_argument("--can-publish", action="store_true")
    send = subparsers.add_parser("send")
    send.add_argument("room")
    send.add_argument("message")
    delete = subparsers.add_parser("delete")
    delete.add_argument("room")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
