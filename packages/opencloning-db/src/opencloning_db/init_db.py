"""
Initialize the database: create tables and seed from cloning_strategy.json.
Run this script manually when you need to (re)create the database.
"""

import json
import os
import glob
from pathlib import Path
import opencloning_linkml.datamodel.models as opencloning_models
from sqlalchemy.orm import Session
from sqlalchemy import select
from opencloning_db.auth.security import get_password_hash
from opencloning_db.config import Config, get_config
from opencloning_db.models import (
    Base,
    Line,
    Primer,
    SequenceInLine,
    SequenceSample,
    Tag,
    SequenceType,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from opencloning_db.db import cloning_strategy_to_db, create_sequencing_file, get_engine


def init_db(config: Config):
    if config.database_path is not None and os.path.exists(config.database_path):
        os.remove(config.database_path)

    os.makedirs(config.sequence_files_dir, exist_ok=True)
    os.makedirs(config.sequencing_files_dir, exist_ok=True)

    engine = get_engine(config)
    Base.metadata.create_all(engine)

    cloning_strategies = []
    file_names = []
    data_dir = Path(__file__).resolve().parent / 'init_db'
    for file in glob.glob(str(data_dir / '*.json')):
        with open(file) as f:
            cloning_strategies.append(opencloning_models.CloningStrategy.model_validate(json.load(f)))
            file_names.append(os.path.basename(file))

    with Session(engine) as session:
        last_seq = None
        sequencing_sequence = None
        # Dummy user and workspace for development purposes (without access)
        other_workspace_user = User(
            email='other-workspace-user@example.com',
            display_name='Other Workspace User',
            password_hash=get_password_hash('password'),
            is_instance_admin=False,
        )
        other_workspace = Workspace(name='Other Workspace')

        # Dummy view-only user
        view_only_user = User(
            email='view-only-user@example.com',
            display_name='View Only User',
            password_hash=get_password_hash('password'),
            is_instance_admin=False,
        )

        # Dev-only: replace with env-driven or unset password before production.
        bootstrap_user = User(
            email='bootstrap@example.com',
            display_name='Bootstrap User',
            password_hash=get_password_hash('password'),
            is_instance_admin=True,
        )
        workspace = Workspace(name='Bootstrap Workspace')
        session.add_all([bootstrap_user, workspace, other_workspace_user, other_workspace, view_only_user])
        session.flush()
        session.add(
            WorkspaceMembership(
                user_id=bootstrap_user.id,
                workspace_id=workspace.id,
                role=WorkspaceRole.owner,
            )
        )

        session.add(
            WorkspaceMembership(
                user_id=other_workspace_user.id,
                workspace_id=other_workspace.id,
                role=WorkspaceRole.owner,
            )
        )

        session.add(
            WorkspaceMembership(
                user_id=view_only_user.id,
                workspace_id=workspace.id,
                role=WorkspaceRole.viewer,
            )
        )

        parent_strain = Line(uid='parent_strain', workspace_id=workspace.id)
        session.add(parent_strain)
        for cloning_strategy, file_name in zip(cloning_strategies, file_names):
            tag_name = os.path.basename(file_name).split('.')[0]
            tag = Tag(name=tag_name, workspace_id=workspace.id)
            session.add(tag)
            sequences, id_mappings = cloning_strategy_to_db(cloning_strategy, session, workspace.id)
            new_line = Line(uid=f"{tag_name}-line", workspace_id=workspace.id, parents=[parent_strain])
            for seq in sequences:
                if seq.name in ['entry_clone_lacZ']:
                    continue
                if seq.sequence_type == SequenceType.allele or seq.sequence_type == SequenceType.plasmid:
                    new_line.sequences_in_line.append(SequenceInLine(sequence=seq))
            new_line.tags.append(tag)
            session.add(new_line)

            for seq in sequences:
                seq.tags.append(tag)
            last_seq = sequences[-1]
            if cloning_strategy.description == 'sequencing':
                sequencing_sequence = last_seq
            session.add(
                SequenceSample(
                    uid=f"{tag_name}-sample",
                    sequence_id=last_seq.id,
                    uid_workspace_id=workspace.id,
                )
            )

        # Find the primer that is used for testing, and add a uid to it
        test_primer = session.scalar(select(Primer).where(Primer.name == 'fwd_restriction_then_ligation'))
        test_primer.uid = 'ML7'
        test_primer.uid_workspace_id = workspace.id
        tag = session.scalar(select(Tag).where(Tag.name == 'restriction_then_ligation'))
        test_primer.tags.append(tag)
        session.add(test_primer)

        for file in glob.glob(str(data_dir / 'sequencing_data' / '*')):
            with open(file, 'rb') as f:
                content = f.read()
            file_name = os.path.basename(file)
            session.add(create_sequencing_file(sequencing_sequence, content, file_name))

        # Add primer that is not linked to any source
        pydantic_primer = opencloning_models.Primer(id=0, name='no_source_primer', sequence='GGTTaaCCaaa')
        no_source_primer = Primer.from_pydantic(pydantic_primer, workspace.id)
        session.add(no_source_primer)

        # seq: Sequence = session.scalar(select(Sequence).where(Sequence.name == 'entry_clone_lacZ'))
        # pydantic_seq = seq.to_pydantic_sequence()
        # # Add itself as sequencing data twice, and sample id to the sequence
        # session.add(create_sequencing_file(seq, pydantic_seq.file_content.encode('utf-8'), 'entry_clone_lacZ.gb'))
        # session.add(create_sequencing_file(seq, pydantic_seq.file_content.encode('utf-8'), 'entry_clone_lacZ2.gb'))
        # session.add(SequenceSample(uid='entry_clone_lacZ-sample', sequence_id=seq.id, uid_workspace_id=workspace.id))
        session.commit()

    print('Database initialized successfully.')

    # from sqlalchemy.schema import CreateTable
    # from sqlalchemy.dialects import postgresql
    # sql_file_content = ''

    # # Print DDL for all tables in the database
    # for table in Base.metadata.tables.values():
    #     sql_file_content += str(CreateTable(table).compile(dialect=postgresql.dialect()))

    # with open('postgres_ddl.sql', 'w') as f:
    #     f.write(sql_file_content)


if __name__ == '__main__':  # pragma: no cover
    config = get_config()
    init_db(config)
