# gupshup-matrix


WhatsApp Matrix-Gupshup <-> Matrix bridge built using [mautrix-python](https://github.com/mautrix/python)

This bridge is based on:

 - [mautrix-twilio](https://github.com/tulir/mautrix-twilio)
 - [mautrix-instagram](https://github.com/mautrix/instagram)
 - [mautrix-signal](https://github.com/mautrix/signal)


## Installation

The first step is to have an account on the https://www.gupshup.io/auth/login platform. Then you must create a gupshup application.

![image](https://user-images.githubusercontent.com/50601186/181797721-cd041594-3afe-444d-9804-5ec96bc53323.png)

Now choose the Access API option:
![image](https://user-images.githubusercontent.com/50601186/181797944-62cb775b-7544-49d6-9118-18c5acf61b98.png)

### Documentation

NOTE: This bridge is inspired by the mautrix bridges, so you can follow the documentation of these bridges.
[Bridge setup](https://docs.mau.fi/bridges/python/setup.html)
(or [with Docker](https://docs.mau.fi/bridges/general/docker-setup.html))

Docker image: `bramenn/gupshup-matrix:latest`

### Register a Gupsgup application on the bridge

- Create a room without encryption
- Then invite the bridge bot (you must have the user registered in the config section `bridge.permissions` as admin)
- Send the command `register-app <gs_app_name> <gs_app_phone> <api_key> <app_id> <app_id>`
- you can now start receiving incoming messages on the registered number


## Discussion

Matrix room:

[`#gupshup-bridge:matrix.org`](https://matrix.to/#/#gupshup-bridge:matrix.org)
