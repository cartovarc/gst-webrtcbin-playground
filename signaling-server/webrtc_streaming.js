class WebRTCStreaming {
    constructor() { }

    initialize(device_id, video_element, audio_element) {

        this.firebaseConfig = {

        };

        firebase.initializeApp(this.firebaseConfig);

        this.pc = null;
        this.use_stun = true;
        this.video_element = document.getElementById(video_element);
        this.audio_element = document.getElementById(audio_element);

        let requestId = "newRequest";
        let clientId = "INAq9J4xdyYZWkLZBltq";
        let deviceId = "cOpVPvoCZsGcLbUnaCmp";

        const db = firebase.firestore();

        // add peerRequest
        this.peerRequestRef = db.collection('clients')
            .doc(clientId)
            .collection("devices")
            .doc(deviceId)
            .collection("peerRequests")
            .doc(requestId)
    }

    async sendSDP(sdp) {
        const data = {
            peerSDP: sdp,
        };


        let res = await this.peerRequestRef.set(data);
        if (!res) {
            console.log("Success");
        } else {
            console.error("ERROR", res);
            return;
        }
    }

    async waitSDP() {
        let me = this;
        me.peerRequestRef.onSnapshot(snapshot => {
            let data = snapshot.data();
            console.log(data);
            if (data["deviceSDP"]) {
                let sdp = data["deviceSDP"];
                console.log(JSON.parse(sdp));
                me.pc.setRemoteDescription(JSON.parse(sdp));
            }
        })
    }

    async listenIceCandidates() {
        let me = this;
        me.peerRequestRef.collection("iceCandidates").onSnapshot(snapshot => {
            let data = snapshot.data();
            console.log("iceCandidate", data);
        })
    }

    negotiate() {
        let me = this;
        this.pc.addTransceiver('video', {
            direction: 'recvonly'
        });
        this.pc.addTransceiver('audio', {
            direction: 'recvonly'
        });
        return this.pc.createOffer().then(function (offer) {
            return me.pc.setLocalDescription(offer);
        }).then(function () {
            // wait for ICE gathering to complete
            return new Promise(function (resolve) {
                if (me.pc.iceGatheringState === 'complete') {
                    resolve();
                } else {
                    function checkState() {
                        if (me.pc.iceGatheringState === 'complete') {
                            me.pc.removeEventListener('icegatheringstatechange', checkState);
                            resolve();
                        }
                    }
                    me.pc.addEventListener('icegatheringstatechange', checkState);
                }
            });
        }).then(function () {
            let sdp = me.pc.localDescription;
            me.listenIceCandidates();
            me.sendSDP(JSON.stringify(sdp));
            me.waitSDP();
        });
    }

    start() {
        let config = {
            sdpSemantics: 'unified-plan'
        };

        if (this.use_stun) {
            config.iceServers = [{ urls: "stun:stun.services.mozilla.com" },
            { urls: "stun:stun.l.google.com:19302" }];
        }

        this.pc = new RTCPeerConnection(config);

        // connect audio / video
        let me = this;
        this.pc.addEventListener('track', function (evt) {
            console.log("new track", evt.streams);
            if (evt.track.kind == 'video') {
                me.video_element.srcObject = evt.streams[0];
            } else {
                me.audio_element.srcObject = evt.streams[0];
            }
        });

        this.negotiate();
    }

    stop() {
        // close peer connection
        let me = this;
        setTimeout(function () {
            me.pc.close();
        }, 500);
    }
}