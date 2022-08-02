#!/bin/sh

# Define functions.
function fixperms {
	chown -R $UID:$GID /data /opt/gupshup-matrix
}

cd /opt/gupshup-matrix

if [ ! -f /data/config.yaml ]; then
	cp gupshup_matrix/example-config.yaml /data/config.yaml
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

fixperms
exec su-exec $UID:$GID python3 -m gupshup_matrix -c /data/config.yaml
