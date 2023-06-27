#!/bin/sh
cd /opt/gupshup-matrix

# Define functions.
function fixperms {
	chown -R $UID:$GID /data

	# /opt/gupshup-matrix is read-only, so disable file logging if it's pointing there.
	if [[ "$(yq e '.logging.handlers.file.filename' /data/config.yaml)" == "./gupshup-matrix.log" ]]; then
		yq -I4 e -i 'del(.logging.root.handlers[] | select(. == "file"))' /data/config.yaml
		yq -I4 e -i 'del(.logging.handlers.file)' /data/config.yaml
	fi
}


if [ ! -f /data/config.yaml ]; then
	cp example-config.yaml /data/config.yaml
	echo "Didn't find a config file."
	echo "Copied default config file to /data/config.yaml"
	echo "Modify that config file to your liking."
	echo "Start the container again after that to generate the registration file."
	fixperms
	exit
fi

if [ ! -f /data/registration.yaml ]; then
	python3 -m gupshup_matrix -g -c /data/config.yaml -r /data/registration.yaml
	echo "Didn't find a registration file."
	echo "Generated one for you."
	echo "Copy that over to synapses app service directory."
	fixperms
	exit
fi

if [ "$1" = "dev" ]; then
	pip install --ignore-installed -r requirements-dev.txt
    watchmedo auto-restart -R -p="*.py" -d="." /opt/gupshup-matrix/docker-run.sh
fi

fixperms
exec su-exec $UID:$GID python3 -m gupshup_matrix -c /data/config.yaml
