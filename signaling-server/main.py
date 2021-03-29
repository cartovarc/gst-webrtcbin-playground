import random
import json
import ssl
import websockets
import asyncio
import sys
import json
import argparse
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')

from gi.repository import Gst  # noqa: E402
from gi.repository import GstWebRTC  # noqa: E402
from gi.repository import GstSdp  # noqa: E402




PIPELINE_DESC = '''
webrtcbin
    name=sendonly
    bundle-policy=max-bundle
    stun-server=stun://stun.l.google.com:19302
 rtspsrc location=rtsp://admin:compuaras19@192.168.100.187:554/cam/realmonitor?channel=1&subtype=0 ! queue ! rtpjitterbuffer latency=500 ! rtph264depay ! h264parse ! omxh264dec ! nvvidconv ! queue ! video/x-raw(memory:NVMM), width=(int)640, height=(int)480, format=(string)I420 ! omxvp8enc control-rate=2 bitrate=150000 ! rtpvp8pay ! queue ! application/x-rtp,media=video,encoding-name=VP8,payload=96 ! sendonly.
 audiotestsrc
    is-live=true
    wave=red-noise !
 audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay ! queue !
 application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! sendonly.
'''


# PIPELINE_DESC = '''
# webrtcbin
#     name=sendonly
#     bundle-policy=max-bundle
#     stun-server=stun://stun.l.google.com:19302
#  tcpclientsrc
#     port=11112
#     host=192.168.100.203
#     do-timestamp=true !
#  h264parse ! omxh264dec ! nvvidconv ! queue !
#  omxvp8enc control-rate=2 bitrate=650000 ! rtpvp8pay !
#  queue ! application/x-rtp,media=video,encoding-name=VP8,payload=96 ! sendonly.
#  audiotestsrc
#     is-live=true
#     wave=red-noise !
#  audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay ! queue !
#  application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! sendonly.
# '''

class WebRTCClient:
    def __init__(self, device_id):
        self.conn = None
        self.pipe = None
        self.webrtc = None
        
        # Initialize firebase
        cred = credentials.Certificate('firebase_credentials.json')
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://aras-cloud.firebaseio.com'
        })

        self.listen_play_requests()


    def listen_play_requests(self):
        requestId = "newRequest"
        clientId = "INAq9J4xdyYZWkLZBltq"
        deviceId = "cOpVPvoCZsGcLbUnaCmp"

        db_firestore = firestore.client()
        ref_play_request = db_firestore.collection('clients').document(clientId).collection("devices").document(deviceId).collection("peerRequests").document(requestId)


        def on_snapshot(doc_snapshot, changes, read_time):
            play_request = doc_snapshot[0].to_dict()
            if "peerSDP" in play_request:
                self.start_pipeline()
                peer_sdp = play_request["peerSDP"]
                self.handle_sdp(peer_sdp)

        ref_play_request.on_snapshot(on_snapshot)


    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print("Sending offer:", text)
        msg = json.dumps({'type': 'offer', 'sdp': text})

        requestId = "newRequest"
        clientId = "INAq9J4xdyYZWkLZBltq"
        deviceId = "cOpVPvoCZsGcLbUnaCmp"

        db_firestore = firestore.client()
        ref_play_request = db_firestore.collection('clients').document(clientId).collection("devices").document(deviceId).collection("peerRequests").document(requestId)
        ref_play_request.set({"deviceSDP": msg})


    def on_offer_created(self, promise, _, __):
        print("on_offer_created")
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value("offer")
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        print("on_negotiation_needed")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created,
                                                   element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        print("send_ice_candidate_message")
        icemsg = json.dumps(
            {'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}}
        )


        requestId = "newRequest"
        clientId = "INAq9J4xdyYZWkLZBltq"
        deviceId = "cOpVPvoCZsGcLbUnaCmp"

        db_firestore = firestore.client()
        ref_ice_candidate = db_firestore.collection('clients').document(clientId).collection("devices").document(deviceId).collection("peerRequests").document(requestId).collection("iceCandidates").document("candidate")
        ref_ice_candidate.set({"hola", "mundo"})

    def start_pipeline(self):
        print("start_pipeline")
        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        self.webrtc = self.pipe.get_by_name('sendonly')
        self.webrtc.connect('on-negotiation-needed',
                            self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate',
                            self.send_ice_candidate_message)
        self.pipe.set_state(Gst.State.PLAYING)

    def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg
            assert(sdp['type'] == 'offer')
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


if __name__ == "__main__":
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument('device_id', help='String ID of the peer to connect to')
    args = parser.parse_args()
    c = WebRTCClient(args.device_id)
    loop = asyncio.get_event_loop()
    loop.run_forever()
    # loop.run_until_complete(c.connect())
    # res = loop.run_until_complete(c.loop())
    sys.exit(res)
