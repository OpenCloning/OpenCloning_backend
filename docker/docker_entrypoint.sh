# APP_TARGET: which app to run — must be exactly one of:
#   cloning  -> opencloning.main:app
#   db       -> opencloning_db.combined:app
#
# WEB_CONCURRENCY: Gunicorn worker processes (default: 2).
# ROOT_PATH: optional subpath prefix (applied by OpenCloningUvicornWorker).

case "${APP_TARGET}" in
    cloning) APP_MODULE=opencloning.main ;;
    db) APP_MODULE=opencloning_db.combined ;;
    *)
        echo "Error: APP_TARGET must be cloning or db" >&2
        exit 1
        ;;
esac

GUNICORN_ARGS=(
    -k opencloning.gunicorn_worker.OpenCloningUvicornWorker
    -w "${WEB_CONCURRENCY:-2}"
    --bind 0.0.0.0:8000
    --timeout 20
    --access-logfile -
    --error-logfile -
    "${APP_MODULE}:app"
)

if [ "$USE_HTTPS" = "true" ]; then
    echo "Using HTTPS"
    if [ ! -f "/certs/key.pem" ] || [ ! -f "/certs/cert.pem" ] || [ ! -r "/certs/key.pem" ] || [ ! -r "/certs/cert.pem" ]; then
        echo "Error: TLS certificate files /certs/key.pem and /certs/cert.pem must both exist and be readable"
        exit 1
    fi
    exec gunicorn "${GUNICORN_ARGS[@]}" --keyfile /certs/key.pem --certfile /certs/cert.pem
else
    echo "Using HTTP"
    exec gunicorn "${GUNICORN_ARGS[@]}"
fi
