# homeauto
Systems and diagrams for home automation

flowchart LR
  %% ================================
  %% BACKBONE / NETWORK EDGE
  %% ================================
  INET((Internet))
  ONT([Fiber / ONT])
  BRIDGE[C4000XG\nTransparent Bridge]
  ROUTER[Your Router/Firewall\n• WAN: PPPoE/IPoE (VLAN if req)\n• LAN: DHCP ON\n• DNS handed to clients = ORIN (Pi-hole)\n• IPv6 RA/DHCPv6 → ORIN as DNS]
  SWITCH[[LAN Switch / Fabric]]

  INET --- ONT --> BRIDGE --> ROUTER --> SWITCH

  %% ================================
  %% CORE ORCHESTRATOR (ORIN)
  %% ================================
  subgraph ORIN[Jetson ORIN — "the conductor"]
    direction TB
    subgraph ORIN_STACK[Docker stack on ORIN]
      direction LR
      HA[Home Assistant :8123\nDashboards, Automations, Vivint, Google Cals]
      NODERED[Node-RED :1880\nFlows, Schedules]
      MQTT[ Mosquitto :1883\nMessage Bus ]
      VIVINT[HACS: Vivint\nPanel/Sensors/Locks/RTSP modes]
      WYOMING[Local Voice (Wyoming)\nopenWakeWord → Whisper STT → Piper TTS]
      Pihole[Pi-hole :53/:8081\nDNS (LAN) + optional DHCP OFF]
      Unbound[Unbound :5335\nValidating Recursive DNS]
      PORTALS[Portainer • Guacamole • Caddy\nAdmin & UI access]
      TAILSCALE[Tailscale\nPrivate remote access + Tailnet DNS]
      %% Media / Audio brain
      SNAPSERVER[Snapserver :1780\nMulti-stream, synced audio]
      MOPIDY[Mopidy → /tmp/snapfifo_music\nNAS, Bandcamp, Webradio]
      LIBRESPOT[librespot → /tmp/snapfifo_spotify\nSpotify Connect sink]
      VINYL_SRC[ALSA/TCP line-in\nUSB ADC near TT or ffmpeg push]
      OCTOFARM[OctoFarm / Repetier-Server\nPrint-farm control/UI]
      %% Optional research/doc
      MINIFLUX[Miniflux (RSS) • Paperless-ngx (OCR/docs)\n(optional now, add later)]
    end

    %% Snapserver streams (named)
    MUSIC(["stream: music"])
    SPOT(["stream: spotify"])
    VINYL(["stream: vinyl"])
    NOTIFY(["stream: notify (priority)"])

    %% Wire audio sources to streams
    MOPIDY -->|raw PCM FIFO| MUSIC
    LIBRESPOT -->|raw PCM FIFO| SPOT
    VINYL_SRC -->|ALSA or TCP 1704| VINYL

    %% HA voice → notify stream
    WYOMING -->|Piper TTS\n(HA tts.speak)| NOTIFY

    %% DNS path
    Pihole -->|upstream 127.0.0.1#5335| Unbound
  end

  %% ORIN on the LAN
  SWITCH --- ORIN

  %% ================================
  %% STORAGE / WORKSTATIONS / EDGES
  %% ================================
  NAS[(NAS / File Server)\nMusic, Docs, Backups]
  MACPRO[Mac Pro 3,1 (Studio Workstation)\nREAPER (Web Remote + OSC)]
  NANO_A[Jetson NANO-A\nFrigate + TensorRT\nRTSP cams → detection → MQTT]
  NANO_B[Jetson NANO-B\nOctoPrint host (USB→Printer #1)\n+ MQTT plugin]

  SWITCH --- NAS
  SWITCH --- MACPRO
  SWITCH --- NANO_A
  SWITCH --- NANO_B

  %% REAPER control path
  HA -- HTTP/OSC triggers --> MACPRO
  NODERED -- HTTP/OSC macros --> MACPRO

  %% Cameras/Frigate path
  NANO_A -- MQTT events --> MQTT
  HA --- VIVINT
  VIVINT --> HA
  VIVINT -. optional RTSP .-> NANO_A

  %% Print farm path
  NANO_B -->|OctoPrint API+MQTT| OCTOFARM
  OCTOPI[OctoPi / Klipper nodes\nPrinters #2/#3]
  SWITCH --- OCTOPI
  OCTOPI -->|Moonraker/OctoPrint| OCTOFARM
  OCTOFARM --> MQTT
  HA <-- MQTT events (start/fail/temps) --> MQTT

  %% ================================
  %% DNS / CLIENTS FLOW
  %% ================================
  subgraph DNS_PATH[DNS & Privacy]
    direction LR
    CLIENTS[[All LAN Clients]]
    CLIENTS -->|DNS queries :53| Pihole --> Unbound --> INET
  end
  ROUTER -- DHCP hands out\nORIN (Pi-hole) v4/v6 as DNS --> CLIENTS

  %% ================================
  %% MULTI-ROOM AUDIO — PER-ROOM SOURCE CONTROL
  %% ================================
  subgraph AUDIO[Multi-room audio (per-room sources)]
    direction TB
    SNAPWEB[Snapweb UI :1780\nGroup/Stream control]
    HA_SRC[HA "Source Select" tiles\n(input_select + JSON-RPC)]
    subgraph GROUPS[Snapcast Groups (rooms)]
      direction LR
      G_STUDIODN[[Group: STUDIO_DN\nclient: snapclient + DAC/amp]]
      G_DINING[[Group: DINING\nclient: snapclient + DAC/amp]]
      G_STUDIOUP[[Group: STUDIO_UP\nclient: snapclient + DAC/amp]]
    end

    %% Control planes
    SNAPWEB -->|Group.SetStream\n(assign stream)| SNAPSERVER
    HA_SRC -->|JSON-RPC → Group.SetStream| SNAPSERVER

    %% Each group can select any stream (dotted = selectable)
    G_STUDIODN -.-> MUSIC
    G_STUDIODN -.-> SPOT
    G_STUDIODN -.-> VINYL

    G_DINING -.-> MUSIC
    G_DINING -.-> SPOT
    G_DINING -.-> VINYL

    G_STUDIOUP -.-> MUSIC
    G_STUDIOUP -.-> SPOT
    G_STUDIOUP -.-> VINYL

    %% Spoken notifications (room-scoped)
    HA -->|snapcast.snapshot → tts.speak (Piper) → snapcast.restore| G_DINING
    WYOMING --> NOTIFY
    NOTIFY --> SNAPSERVER
  end

  %% Connect audio control to ORIN stack
  ORIN_STACK --> SNAPSERVER
  ORIN_STACK --> HA
  ORIN_STACK --> WYOMING
  SNAPWEB --- SNAPSERVER
  HA_SRC --- HA

  %% ================================
  %% REMOTE / ADMIN ACCESS
  %% ================================
  subgraph REMOTE[Off-site & Admin]
    direction LR
    TAILCLIENT[(Laptops/Phones on Tailnet)]
    TAILCLIENT -->|Private access| TAILSCALE
    TAILSCALE --> HA
    TAILSCALE --> SNAPSERVER
    TAILSCALE --> OCTOFARM
    TAILSCALE --> Pihole
    PORTALS --- HA
    PORTALS --- ORIN
  end
