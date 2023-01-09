import uuid
from pathlib import Path
from unittest.mock import Mock

from folio_uuid.folio_namespaces import FOLIONamespaces

from folio_migration_tools.extradata_writer import ExtradataWriter
from folio_migration_tools.migration_report import MigrationReport
from folio_migration_tools.migration_tasks.migration_task_base import MigrationTaskBase
from folio_migration_tools.migration_tasks.organization_transformer import (
    OrganizationMapper,
)
from folio_migration_tools.migration_tasks.organization_transformer import (
    OrganizationTransformer,
)


def test_get_object_type():
    assert OrganizationTransformer.get_object_type() == FOLIONamespaces.organizations


def test_subclass_inheritance():
    assert issubclass(OrganizationTransformer, MigrationTaskBase)

# Organizations -- Post-transformation cleanup
def test_remove_organization_types_pre_morning_glory():
    rec = {
        "id": "c15aabf7-8a4a-5a6c-8c44-2a51f17db6a9",
        "name": "Academic International Press",
        "organizationTypes": ["fc54327d-fd60-4f6a-ba37-a4375511b91b"],
    }

    clean_org_lotus = OrganizationTransformer.clean_org_type_pre_morning_glory(
        OrganizationTransformer, rec, "lotus"
    )
    assert clean_org_lotus == {
        "id": "c15aabf7-8a4a-5a6c-8c44-2a51f17db6a9",
        "name": "Academic International Press",
    }

    rec = {
        "id": "c15aabf7-8a4a-5a6c-8c44-2a51f17db6a9",
        "name": "Academic International Press",
        "organizationTypes": ["fc54327d-fd60-4f6a-ba37-a4375511b91b"],
    }

    clean_org_morning_glory = OrganizationTransformer.clean_org_type_pre_morning_glory(
        OrganizationTransformer, rec, "morning_glory"
    )
    assert clean_org_morning_glory == {
        "id": "c15aabf7-8a4a-5a6c-8c44-2a51f17db6a9",
        "name": "Academic International Press",
        "organizationTypes": ["fc54327d-fd60-4f6a-ba37-a4375511b91b"],
    }


def test_create_and_link_contacts():
    mocked_organization_transformer = Mock(spec=OrganizationTransformer)
    mocked_organization_transformer.contacts_cache = {}
    mocked_organization_transformer.extradata_writer = ExtradataWriter(Path(""))
    mocked_organization_transformer.extradata_writer.cache = []
    mocked_organization_transformer.mapper = Mock(spec=OrganizationMapper)
    mocked_organization_transformer.mapper.migration_report = Mock(spec=MigrationReport)
    mocked_organization_transformer.clean_addresses = OrganizationTransformer.clean_addresses

    recs = [
        {
            "name": "MyCompany",
            "contacts": [
                {
                    "firstName": "Jane",
                    "lastName": "Deer",
                    "emailAddresses": [{"value": "me(at)me.com"}],
                },
                {
                    "firstName": "John",
                    "lastName": "Doe",
                    "addresses": [{"addressLine1": "MyStreet"}, {"city": "Bogotá"}],
                    "emailAddresses": [{"value": "andme(at)me.com"}],
                },
            ],
        },
        {
            "name": "YourCompany",
            "contacts": [
                {
                    "firstName": "Jane",
                    "lastName": "Deer",
                    "emailAddresses": [{"value": "me(at)me.com"}],
                }
            ],
        },
    ]

    for rec in recs:
        OrganizationTransformer.create_extradata_objects(mocked_organization_transformer, rec)

    # Check that UUIDs have been added to the organization record
    assert all(uuid.UUID(str(value), version=4) for value in rec["contacts"])

    # Check that all the assigned UUIDs are in the extradata writer cache
    assert all(
        str(id) in str(mocked_organization_transformer.extradata_writer.cache)
        for id in rec["contacts"]
    )

    # Check that all the assigned uuids are in the cache (for deduplication)
    assert all(
        str(id) in mocked_organization_transformer.contacts_cache.keys() for id in rec["contacts"]
    )

    # Check that contacts have been added to the extra data cache
    assert "contacts" in mocked_organization_transformer.extradata_writer.cache[0]
    assert any(
        "Jane" in contact for contact in mocked_organization_transformer.extradata_writer.cache
    )
    assert any(
        "Deer" in contact for contact in mocked_organization_transformer.extradata_writer.cache
    )
    assert any(
        "John" in contact for contact in mocked_organization_transformer.extradata_writer.cache
    )

    # Check that reoccuring contacts are deduplicated
    assert str(mocked_organization_transformer.extradata_writer.cache).count("Jane") == 1


def test_contact_formatting_and_content():
    # Check that contacts in the extradata writer contain the right information
    mocked_organization_transformer = Mock(spec=OrganizationTransformer)
    mocked_organization_transformer.contacts_cache = {}
    mocked_organization_transformer.extradata_writer = ExtradataWriter(Path(""))
    mocked_organization_transformer.extradata_writer.cache = []
    mocked_organization_transformer.mapper = Mock(spec=OrganizationMapper)
    mocked_organization_transformer.mapper.migration_report = Mock(spec=MigrationReport)
    mocked_organization_transformer.clean_addresses = OrganizationTransformer.clean_addresses

    recs = [
        {
            "name": "YourCompany",
            "contacts": [
                {
                    "firstName": "June",
                    "lastName": "Day",
                    "addresses": [{"addressLine1": "MyStreet"}, {"city": "Stockholm"}],
                    "phoneNumbers": [{"phoneNumber": "123"}],
                    "emailAddresses": [{"value": "andme(at)me.com"}],
                },
            ],
        },
    ]

    for rec in recs:
        OrganizationTransformer.create_extradata_objects(mocked_organization_transformer, rec)

    assert (
        'contacts\\t{"firstName": "June", "lastName": "Day", '
        '"addresses": [{"addressLine1": "MyStreet"}, {"city": "Stockholm"}], '
        '"phoneNumbers": [{"phoneNumber": "123"}], '
        '"emailAddresses": [{"value": "andme(at)me.com"}]'
        in str(mocked_organization_transformer.extradata_writer.cache)
    )


def test_clean_up_one_address():
    rec = {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "",
                "zipCode": "PO Box 1111",
                "isPrimary": True,
            }
        ]
    }

    clean_address = OrganizationTransformer.clean_addresses(OrganizationTransformer, rec)

    assert clean_address == {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "",
                "zipCode": "PO Box 1111",
                "isPrimary": True,
            }
        ]
    }


def test_clean_up_two_addresses_no_primary():
    rec = {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": False,
            },
            {
                "addressLine1": "Vita Villan",
                "city": "Horred",
                "stateRegion": "BC",
                "zipCode": "20",
                "isPrimary": False,
            },
        ]
    }

    clean_address = OrganizationTransformer.clean_addresses(OrganizationTransformer, rec)

    assert clean_address == {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": True,
            },
            {
                "addressLine1": "Vita Villan",
                "city": "Horred",
                "stateRegion": "BC",
                "zipCode": "20",
                "isPrimary": False,
            },
        ]
    }


def test_clean_up_two_addresses_both_primary():
    """
    Having two primary addresses will be weird in FOLIO. We should be able to
    avoid it by only every mapping one address type as Primary.
    """
    rec = {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": True,
            },
            {
                "addressLine1": "Vita Villan",
                "city": "Horred",
                "stateRegion": "BC",
                "zipCode": "20",
                "isPrimary": True,
            },
        ]
    }

    clean_address = OrganizationTransformer.clean_addresses(OrganizationTransformer, rec)

    assert clean_address == {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": True,
            },
            {
                "addressLine1": "Vita Villan",
                "city": "Horred",
                "stateRegion": "BC",
                "zipCode": "20",
                "isPrimary": True,
            },
        ]
    }


def test_clean_up_two_addresses_one_empty():
    rec = {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": True,
            },
            {"addressLine1": "", "city": "", "stateRegion": "", "zipCode": "", "isPrimary": False},
        ]
    }

    clean_address = OrganizationTransformer.clean_addresses(OrganizationTransformer, rec)

    assert clean_address == {
        "addresses": [
            {
                "addressLine1": "Suite 500 - 655 Typee Rd",
                "city": "Victoria",
                "stateRegion": "BC",
                "zipCode": "",
                "isPrimary": True,
            }
        ]
    }


def test_clean_up_two_addresses_both_empty():
    rec = {
        "addresses": [
            {"addressLine1": "", "city": "", "stateRegion": "", "zipCode": "", "isPrimary": True},
            {"addressLine1": "", "city": "", "stateRegion": "", "zipCode": "", "isPrimary": ""},
        ]
    }

    clean_address = OrganizationTransformer.clean_addresses(OrganizationTransformer, rec)

    assert clean_address == {"addresses": []}

# Contacts

# Interfaces