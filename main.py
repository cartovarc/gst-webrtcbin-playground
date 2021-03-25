import random
import ssl
import websockets
import asyncio
import sys
import json
import argparse

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')

from gi.repository import Gst  # noqa: E402
from gi.repository import GstWebRTC  # noqa: E402
from gi.repository import GstSdp  # noqa: E402


PIPELINE_DESC = '''
webrtcbin
    name=sendrecv
    bundle-policy=max-bundle
    stun-server=stun://stun.l.google.com:19302
 tcpclientsrc
    port=11112
    host=192.168.100.203
    do-timestamp=true !
 h264parse ! omxh264dec ! nvvidconv ! queue !
 omxvp9enc control-rate=2 bitrate=650000 ! rtpvp9pay !
 queue ! application/x-rtp,media=video,encoding-name=VP9,payload=96 ! sendrecv.
 audiotestsrc
    is-live=true
    wave=red-noise !
 audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay ! queue !
 application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! sendrecv.
'''


class WebRTCClient:
    def __init__(self, id_, peer_id, server):
        self.id_ = id_
        self.conn = None
        self.pipe = None
        self.webrtc = None
        self.peer_id = peer_id
        self.server = server or 'wss://webrtc.nirbheek.in:8443'

    async def connect(self):
        sslctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        self.conn = await websockets.connect(self.server, ssl=sslctx)
        await self.conn.send('HELLO %d' % self.id_)

    async def setup_call(self):
        await self.conn.send('SESSION {}'.format(self.peer_id))

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print("Sending offer:", text)
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(msg))
        loop.close()

    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value("offer")
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created,
                                                   element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        icemsg = json.dumps(
            {'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}}
        )
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(icemsg))
        loop.close()

    def start_pipeline(self):
        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.webrtc.connect('on-negotiation-needed',
                            self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate',
                            self.send_ice_candidate_message)
        self.pipe.set_state(Gst.State.PLAYING)

    def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            print('Received answer:\n%s' % sdp)
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(
                GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg
            )
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    def close_pipeline(self):
        self.pipe.set_state(Gst.State.NULL)
        self.pipe = None
        self.webrtc = None

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            if message == 'HELLO':
                await self.setup_call()
            elif message == 'SESSION_OK':
                self.start_pipeline()
            elif message.startswith('ERROR'):
                print(message)
                self.close_pipeline()
                return 1
            else:
                self.handle_sdp(message)
        self.close_pipeline()
        return 0

    async def stop(self):
        if self.conn:
            await self.conn.close()
        self.conn = None


def check_plugins():
    needed = ["opus", "vpx", "nice", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager", "videotestsrc", "audiotestsrc"]
    missing = list(
        filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed)
    )
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True


if __name__ == '__main__':
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument('peerid', help='String ID of the peer to connect to')
    parser.add_argument('--server', help='Signalling server to connect')
    args = parser.parse_args()
    our_id = random.randrange(10, 10000)
    c = WebRTCClient(our_id, args.peerid, args.server)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(c.connect())
    res = loop.run_until_complete(c.loop())
    sys.exit(res)
