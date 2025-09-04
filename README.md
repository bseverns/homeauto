# homeauto
Systems and diagrams for home automation

flowchart LR
  INET((Internet)) --> ONT[ONT / Fiber]
  ONT --> BRIDGE[C4000XG (Transparent Bridge)]
  BRIDGE --> ROUTER[Your Router/Firewall\nWAN: PPPoE/IPoE (+VLAN if needed)\nLAN: DHCP ON\nDNS to clients = ORIN (Pi-hole)]
  ROUTER --> SWITCH[[LAN Switch]]

  SWITCH --> ORIN[Jetson ORIN (Docker stack)\nHA, Node-RED, MQTT, Pi-hole, Unbound,\nSnapserver, Mopidy, librespot, OctoFarm, Tailscale]
  SWITCH --> NAS[(NAS / Files)]
  SWITCH --> MACPRO[Mac Pro 3,1 (REAPER)]
  SWITCH --> NANO_A[Jetson NANO-A (Frigate)]
  SWITCH --> NANO_B[Jetson NANO-B (OctoPrint host)]
  SWITCH --> OCTOPI[OctoPi/Klipper nodes\nPrinters #2/#3]
  SWITCH --> ROOMS[Snapclients in rooms\n(Studio DN, Dining, Studio UP)]

  ROUTER -- "DHCP hands out ORIN as DNS (v4/v6)" --> CLIENTS[[All LAN Clients]]
  CLIENTS -->|DNS :53| PIHOLE[Pi-hole on ORIN] --> UNBOUND[Unbound on ORIN]
end

flowchart TD
  subgraph ORIN[Jetson ORIN ("the conductor")]
    HA[Home Assistant]
    NR[Node-RED]
    MQTT[MQTT (Mosquitto)]
    VIVINT[Vivint (HACS)]
    WY[Local Voice (Wyoming)\nopenWakeWord -> Whisper -> Piper]
    PIHOLE[Pi-hole :53/:8081]
    UNB[Unbound :5335]
    SNAP[Snapserver :1780\nstreams: music / spotify / vinyl / notify]
    MOP[Mopidy -> /tmp/snapfifo_music]
    LIB[librespot -> /tmp/snapfifo_spotify]
    VIN[Vinyl line-in (ALSA or TCP push)]
    OFARM[OctoFarm / Repetier-Server]
    TAIL[Tailscale]
    OPS[Portainer / Guacamole / Caddy]
  end

  %% DNS
  PIHOLE -- "upstream 127.0.0.1#5335" --> UNB

  %% Voice -> HA -> TTS
  WY --> HA
  HA -- "tts.speak (Piper)" --> SNAP

  %% Media -> Snapserver streams
  MOP -- "PCM FIFO -> music" --> SNAP
  LIB -- "PCM FIFO -> spotify" --> SNAP
  VIN -- "ALSA/TCP -> vinyl" --> SNAP

  %% Vivint + HA
  VIVINT <--> HA
  HA <--> MQTT
  NR <--> MQTT
  HA <--> NR

  %% Studio control
  HA -- "HTTP/OSC" --> MACPRO[REAPER on Mac Pro 3,1]
  NR -- "HTTP/OSC macros" --> MACPRO

  %% Print farm
  OFARM <--> HA
  OFARM <--> MQTT
  NANO_B[OctoPrint host] -- "API + MQTT" --> OFARM
  OCTOPI[OctoPi/Klipper] -- "OctoPrint/Moonraker" --> OFARM

  %% Cameras/Vision
  NANO_A[Frigate] -- "RTSP cams + detections" --> MQTT
  HA <--> NANO_A

flowchart LR
  SNAP[Snapserver\nstreams: music | spotify | vinyl | notify]
  MOP[Mopidy -> /tmp/snapfifo_music] -->|music| SNAP
  LIB[librespot -> /tmp/snapfifo_spotify] -->|spotify| SNAP
  VIN[Vinyl line-in (ALSA or TCP)] -->|vinyl| SNAP

  subgraph GROUPS[Snapcast Groups (rooms)]
    SDN[[Group: STUDIO_DN\nsnapclient + DAC/amp]]
    DIN[[Group: DINING\nsnapclient + DAC/amp]]
    SUP[[Group: STUDIO_UP\nsnapclient + DAC/amp]]
  end

  %% Each group may select any stream (we show all bindings explicitly)
  SNAP -- "select stream: music/spotify/vinyl" --> SDN
  SNAP -- "select stream: music/spotify/vinyl" --> DIN
  SNAP -- "select stream: music/spotify/vinyl" --> SUP

  %% Control faces
  SNAPWEB[Snapweb :1780\n(assign stream to group)] --> SNAP
  HA[Home Assistant\n(source tiles via JSON-RPC)] --> SNAP

  %% Scoped notifications (snapshot -> speak -> restore)
  HA -- "snapcast.snapshot" --> DIN
  HA -- "tts.speak (Piper) -> notify" --> SNAP
  SNAP -- "to group (temporary)" --> DIN
  HA -- "snapcast.restore" --> DIN

