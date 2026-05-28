import opencloning_db.db as db_module
from opencloning_db.init_db import load_seed_data
from opencloning_db.storage import ObjectStorage
from opencloning_db.migrations import reset_database


def test_init_db(postgres_test_config_write):
    """Load seed fixtures into the Postgres test DB using the shared test config."""
    postgres_test_config = postgres_test_config_write
    engine = db_module.get_engine(postgres_test_config)
    reset_database(engine)
    load_seed_data(engine)
    storage = ObjectStorage(postgres_test_config)
    assert len(storage.list_keys(postgres_test_config.sequence_objects_prefix)) == 48
    assert len(storage.list_keys(postgres_test_config.sequencing_objects_prefix)) == 3
