##systems for home automation

flowchart LR
  INET(("Internet")) --> ONT["ONT / Fiber"]
  ONT --> BRIDGE["C4000XG (Transparent Bridge)"]
  BRIDGE --> ROUTER["Your Router/Firewall<br/>WAN: PPPoE/IPoE (VLAN if needed)<br/>LAN: DHCP ON<br/>DNS to clients = ORIN (Pi-hole)"]
  ROUTER --> SWITCH["LAN Switch"]

  SWITCH --> ORIN["Jetson ORIN (Docker stack)<br/>HA, Node-RED, MQTT, Pi-hole, Unbound,<br/>Snapserver, Mopidy, librespot, OctoFarm, Tailscale"]
  SWITCH --> NAS["NAS / Files"]
  SWITCH --> MACPRO["Mac Pro 3,1 (REAPER)"]
  SWITCH --> NANO_A["Jetson NANO-A (Frigate)"]
  SWITCH --> NANO_B["Jetson NANO-B (OctoPrint host)"]
  SWITCH --> OCTOPI["OctoPi / Klipper nodes<br/>Printers #2/#3"]
  SWITCH --> ROOMS["Snapclients in rooms<br/>(Studio DN, Dining, Studio UP)"]

  ROUTER -- "DHCP hands out ORIN as DNS (v4/v6)" --> CLIENTS["All LAN Clients"]
  CLIENTS -->|"DNS :53"| PIHOLE["Pi-hole on ORIN"]
  PIHOLE --> UNBOUND["Unbound on ORIN"]

  flowchart TD
  subgraph ORIN["Jetson ORIN (the conductor)"]
    HA["Home Assistant"]
    NR["Node-RED"]
    MQTT["MQTT (Mosquitto)"]
    VIVINT["Vivint (HACS)"]
    WY["Local Voice (Wyoming):<br/>openWakeWord -> Whisper -> Piper"]
    PIHOLE2["Pi-hole :53/:8081"]
    UNB2["Unbound :5335"]
    SNAP["Snapserver :1780<br/>streams: music, spotify, vinyl, notify"]
    MOP["Mopidy -> /tmp/snapfifo_music"]
    LIB["librespot -> /tmp/snapfifo_spotify"]
    VIN["Vinyl line-in (ALSA or TCP push)"]
    OFARM["OctoFarm / Repetier-Server"]
    TAIL["Tailscale"]
    OPS["Portainer / Guacamole / Caddy"]
  end

  PIHOLE2 -- "upstream 127.0.0.1#5335" --> UNB2

  WY --> HA
  HA -- "tts.speak (Piper)" --> SNAP

  MOP -- "PCM FIFO to stream 'music'" --> SNAP
  LIB -- "PCM FIFO to stream 'spotify'" --> SNAP
  VIN -- "ALSA/TCP to stream 'vinyl'" --> SNAP

  VIVINT <--> HA
  HA <--> MQTT
  NR <--> MQTT
  HA <--> NR

  HA -- "HTTP/OSC" --> MACPRO2["REAPER on Mac Pro 3,1"]
  NR -- "HTTP/OSC macros" --> MACPRO2

  OFARM <--> HA
  OFARM <--> MQTT
  NANO_B2["OctoPrint host"] -- "API + MQTT" --> OFARM
  OCTOPI2["OctoPi / Klipper nodes"] -- "OctoPrint or Moonraker" --> OFARM

  NANO_A2["Frigate"] -- "RTSP detections -> MQTT" --> MQTT
  HA <--> NANO_A2

flowchart LR
  SNAP2["Snapserver<br/>streams: music | spotify | vinyl | notify"]
  MOP2["Mopidy -> /tmp/snapfifo_music"] -->|music| SNAP2
  LIB2["librespot -> /tmp/snapfifo_spotify"] -->|spotify| SNAP2
  VIN2["Vinyl line-in (ALSA or TCP)"] -->|vinyl| SNAP2

  subgraph GROUPS["Snapcast Groups (rooms)"]
    SDN["Group: STUDIO_DN<br/>snapclient + DAC/amp"]
    DIN["Group: DINING<br/>snapclient + DAC/amp"]
    SUP["Group: STUDIO_UP<br/>snapclient + DAC/amp"]
  end

  SNAP2 -- "assign stream: music/spotify/vinyl" --> SDN
  SNAP2 -- "assign stream: music/spotify/vinyl" --> DIN
  SNAP2 -- "assign stream: music/spotify/vinyl" --> SUP

  SNAPWEB["Snapweb :1780<br/>(select group -> stream)"] --> SNAP2
  HA2["Home Assistant<br/>(source tiles via JSON-RPC)"] --> SNAP2

  HA2 -- "snapcast.snapshot" --> DIN
  HA2 -- "tts.speak (Piper) -> stream 'notify'" --> SNAP2
  SNAP2 -- "temporary to group" --> DIN
  HA2 -- "snapcast.restore" --> DIN
