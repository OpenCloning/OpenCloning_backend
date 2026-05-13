import os
from opencloning_db.init_db import init_db


def test_init_db(postgres_test_config):
    """Seed init_db assets into the Postgres test DB using the shared test config fixture."""
    init_db(postgres_test_config)
    assert len(os.listdir(postgres_test_config.sequence_files_dir)) == 48
    assert len(os.listdir(postgres_test_config.sequencing_files_dir)) == 3
