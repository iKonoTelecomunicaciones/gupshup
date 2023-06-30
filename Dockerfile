FROM docker.io/alpine:3.14

RUN apk add --no-cache \
      python3 py3-pip py3-setuptools py3-wheel \
      py3-virtualenv \
      py3-pillow \
      py3-aiohttp \
      py3-magic \
      py3-ruamel.yaml \
      py3-commonmark \
      py3-phonenumbers \
      # Other dependencies
      ffmpeg \
      ca-certificates \
      su-exec \
      # encryption
      py3-olm \
      py3-cffi \
      py3-pycryptodome \
      py3-unpaddedbase64 \
      py3-future \
      bash \
      curl \
      jq \
      yq

COPY requirements.txt /opt/gupshup-matrix/requirements.txt
COPY requirements-dev.txt /opt/gupshup-matrix/requirements-dev.txt
WORKDIR /opt/gupshup-matrix
RUN apk add --virtual .build-deps python3-dev libffi-dev build-base \
 && pip3 install -r requirements.txt \
 && apk del .build-deps

COPY . /opt/gupshup-matrix
RUN apk add git && pip3 install .[all] && apk del git \
  # This doesn't make the image smaller, but it's needed so that the `version` command works properly
  && cp gupshup_matrix/example-config.yaml . && rm -rf gupshup_matrix

ENV UID=1337 GID=1337
VOLUME /data

CMD ["/opt/gupshup-matrix/docker-run.sh"]
