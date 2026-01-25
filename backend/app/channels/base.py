from dataclasses import dataclass


@dataclass
class IncomingMessage:
    channel: str
    from_id: str
    text: str


@dataclass
class OutgoingMessage:
    channel: str
    to_id: str
    text: str


class ChannelAdapter:
    name = "base"

    async def send(self, message: OutgoingMessage):
        raise NotImplementedError
