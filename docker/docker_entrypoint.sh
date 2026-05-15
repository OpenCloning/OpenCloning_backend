# Only add --root-path if ROOT_PATH is not empty, otherwise uvicorn will throw an error
#
# APP_TARGET: which app to run — must be exactly one of:
#   cloning  -> opencloning.main:app
#   db       -> opencloning_db.combined:app

case "${APP_TARGET}" in
    cloning) APP_MODULE=opencloning.main ;;
    db) APP_MODULE=opencloning_db.combined ;;
    *)
        echo "Error: APP_TARGET must be cloning or db" >&2
        exit 1
        ;;
esac

if [ "$USE_HTTPS" = "true" ]; then
    echo "Using HTTPS"
    if [ ! -f "/certs/key.pem" ] || [ ! -f "/certs/cert.pem" ] || [ ! -r "/certs/key.pem" ] || [ ! -r "/certs/cert.pem" ]; then
        echo "Error: TLS certificate files /certs/key.pem and /certs/cert.pem must both exist and be readable"
        exit 1
    fi
    uvicorn "${APP_MODULE}:app" --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} ${ROOT_PATH:+--root-path ${ROOT_PATH}} --ssl-keyfile /certs/key.pem --ssl-certfile /certs/cert.pem
else
    echo "Using HTTP"
    uvicorn "${APP_MODULE}:app" --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} ${ROOT_PATH:+--root-path ${ROOT_PATH}}
fi
