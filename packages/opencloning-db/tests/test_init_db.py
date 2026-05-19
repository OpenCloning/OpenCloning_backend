from opencloning_db.init_db import init_db
from opencloning_db.storage import ObjectStorage


def test_init_db(postgres_test_config):
    """Seed init_db assets into the Postgres test DB using the shared test config fixture."""
    init_db(postgres_test_config)
    storage = ObjectStorage(postgres_test_config)
    assert len(storage.list_keys(postgres_test_config.sequence_objects_prefix)) == 48
    assert len(storage.list_keys(postgres_test_config.sequencing_objects_prefix)) == 3
