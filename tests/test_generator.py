import pytest
from dbt2lookml.generators import LookmlGenerator, NotImplementedError
from dbt2lookml.utils import Sql
from dbt2lookml.models import (DbtModel, DbtModelMeta, DbtModelColumn, DbtModelColumnMeta, 
                               DbtMetaLooker, DbtModelMetaLooker, DbtCatalogNodeColumn)
from dbt2lookml.enums import (SupportedDbtAdapters, LookerMeasureType, LookerTimeTimeframes, 
                               LookerDateTypes, LookerDateTimeTypes, LookerDateTimeframes,
                               LookerValueFormatName)
from dbt2lookml.exceptions import CliError

import os
import tempfile
import json

@pytest.mark.parametrize("sql,expected", [
    ("${TABLE}.column", "${TABLE}.column"),
    ("${view_name}.field", "${view_name}.field"),
    ("invalid sql", None),  # No ${} syntax
    ("SELECT * FROM table;;", None),  # Invalid ending
    ("${TABLE}.field;;", "${TABLE}.field"),  # Removes semicolons
])
def test_validate_sql(sql, expected):
    """Test SQL validation for Looker expressions"""
    sql_util = Sql()
    assert sql_util.validate_sql(sql) == expected

@pytest.mark.parametrize("bigquery_type,expected_looker_type", [
    ("STRING", "string"),
    ("INT64", "number"),
    ("FLOAT64", "number"),
    ("BOOL", "yesno"),
    ("TIMESTAMP", "timestamp"),
    ("DATE", "date"),
    ("DATETIME", "datetime"),
    ("ARRAY<STRING>", "string"),
    ("STRUCT<name STRING>", "string"),
    ("INVALID_TYPE", None),
])
def test_map_bigquery_to_looker(bigquery_type, expected_looker_type):
    """Test mapping of BigQuery types to Looker types"""
    lookml_generator = LookmlGenerator()
    assert lookml_generator._map_bigquery_to_looker(bigquery_type) == expected_looker_type

def test_dimension_group_time():
    """Test creation of time-based dimension groups"""
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={},
        meta=DbtModelMeta(),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    column = DbtModelColumn(
        name="created_at",
        lookml_name="created_at",
        lookml_long_name="created_at",
        data_type="TIMESTAMP",
        unique_id="test_model.created_at",
        meta=DbtModelColumnMeta()
    )
    
    lookml_generator = LookmlGenerator()
    result = lookml_generator._lookml_dimension_group(column, "time", True, model)
    assert isinstance(result[0], dict)
    assert result[0].get("type") == "time"
    assert result[0].get("timeframes") == LookerTimeTimeframes.values()
    assert result[0].get("convert_tz") == "yes"

def test_dimension_group_invalid_type():
    """Test dimension group creation with invalid type"""
    lookml_generator = LookmlGenerator()
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={},
        meta=DbtModelMeta(),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    column = DbtModelColumn(
        name="created_at",
        lookml_name="created_at",
        lookml_long_name="created_at",
        data_type="TIMESTAMP",
        unique_id="test_model.created_at",
        meta=DbtModelColumnMeta()
    )

    with pytest.raises(NotImplementedError):
        lookml_generator._lookml_dimension_group(column, "invalid_type", True, model)

def test_dimension_group_date():
    """Test creation of date-based dimension groups"""
    lookml_generator = LookmlGenerator()
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={},
        meta=DbtModelMeta(),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )

    # Test with date column
    column = DbtModelColumn(
        name="created_date",
        lookml_name="created_date",
        lookml_long_name="created_date",
        data_type="DATE",
        unique_id="test_model.created_date",
        meta=DbtModelColumnMeta(looker=DbtMetaLooker(
            label="Custom Date Label",
            group_label="Custom Group"
        ))
    )

    dimension_group, dimension_set, _ = lookml_generator._lookml_dimension_group(column, "date", True, model)
    assert dimension_group['type'] == 'date'
    assert dimension_group['convert_tz'] == 'no'
    assert dimension_group['timeframes'] == LookerDateTimeframes.values()
    assert dimension_group['label'] == "Custom Date Label"
    assert dimension_group['group_label'] == "Custom Group"
    assert dimension_group['name'] == "created"  # _date removed
    
    # Check dimension set
    assert dimension_set['name'] == "s_created"
    assert all(tf in dimension_set['fields'] for tf in [f"created_{t}" for t in LookerDateTimeframes.values()])
    #assert dimension_set['label'] == "Custom Date Label"

def test_dimension_group_unsupported_type():
    """Test dimension group creation with unsupported column type"""
    lookml_generator = LookmlGenerator()
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={},
        meta=DbtModelMeta(),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    column = DbtModelColumn(
        name="invalid_type",
        lookml_name="invalid_type",
        lookml_long_name="invalid_type",
        data_type="UNSUPPORTED_TYPE",
        unique_id="test_model.invalid_type",
        meta=DbtModelColumnMeta()
    )

    with pytest.raises(NotImplementedError):
        lookml_generator._lookml_dimension_group(column, "time", True, model)

def test_extract_array_models():
    """Test extraction of array models from columns"""
    columns = [
        DbtCatalogNodeColumn(
            name="items",
            type="ARRAY<STRUCT<name STRING, price FLOAT64>>",
            index=0
        ),
        DbtCatalogNodeColumn(
            name="id",
            type="INT64",
            index=1
        )
    ]
    
    lookml_generator = LookmlGenerator()
    array_columns = lookml_generator._extract_array_models(columns)
    assert len(array_columns) == 1
    assert array_columns[0].name == "items"
    assert array_columns[0].data_type.startswith("ARRAY")

def test_get_view_label():
    """Test getting view label from model"""
    lookml_generator = LookmlGenerator()
    
    # Test with looker meta label
    model = type('TestModel', (), {
        'meta': type('Meta', (), {
            'looker': type('Looker', (), {'label': 'Custom Label'})()
        })(),
        'name': 'test_model'
    })
    assert lookml_generator._get_view_label(model) == 'Custom Label'
    
    # Test fallback to model name
    model = type('TestModel', (), {
        'meta': type('Meta', (), {
            'looker': type('Looker', (), {'label': None})()
        })(),
        'name': 'test_model'
    })
    assert lookml_generator._get_view_label(model) == 'Test Model'
    
    # Test with no name
    model = type('TestModel', (), {
        'meta': type('Meta', (), {
            'looker': type('Looker', (), {'label': None})()
        })(),
    })
    assert lookml_generator._get_view_label(model) is None

def test_get_excluded_array_names():
    """Test getting excluded array names"""
    lookml_generator = LookmlGenerator()
    
    # Create test model with array columns
    array_model = DbtCatalogNodeColumn(
        name="items",
        type="ARRAY<STRUCT<name STRING, price FLOAT64>>",
        index=0
    )
    
    model = type('TestModel', (), {
        'columns': {
            'items': array_model,
            'items.name': DbtCatalogNodeColumn(name="items.name", type="STRING", index=1),
            'items.price': DbtCatalogNodeColumn(name="items.price", type="FLOAT64", index=2),
            'id': DbtCatalogNodeColumn(name="id", type="INT64", index=3)
        }
    })
    
    exclude_names = lookml_generator._get_excluded_array_names(model, [array_model])
    assert len(exclude_names) == 2
    assert 'items' not in exclude_names
    assert 'items.name' in exclude_names
    assert 'items.price' in exclude_names
    assert 'id' not in exclude_names

def test_create_main_view():
    """Test creating main view"""
    lookml_generator = LookmlGenerator()
    
    # Create test model
    model = type('TestModel', (), {
        'relation_name': 'project.dataset.table',
        'columns': {},
        'meta': DbtModelColumnMeta(),
        'unique_id': "test_model",
        'resource_type': "model",
        'schema': "test_schema",
        'description': "Test model",
        'tags': []
    })
    
    view = lookml_generator._create_main_view(model, 'test_view', 'Test View', [])
    assert view['name'] == 'test_view'
    assert view['label'] == 'Test View'
    assert view['sql_table_name'] == 'project.dataset.table'
    assert 'dimensions' not in view
    assert 'dimension_groups' not in view
    assert 'sets' not in view
    assert 'measures' not in view

def test_create_nested_view():
    """Test creating nested view"""
    lookml_generator = LookmlGenerator()
    
    # Create test model with array column
    array_model = DbtModelColumn(
        name="items",
        lookml_name="items",
        lookml_long_name="items",
        data_type="ARRAY<STRUCT<name STRING, price FLOAT64>>",
        inner_types=["STRUCT<name STRING, price FLOAT64>"],
        unique_id="test_model.items",
        meta=DbtModelColumnMeta()
    )
    
    model = type('TestModel', (), {
        'columns': {
            'items': array_model,
            'items.name': DbtModelColumn(
                name="items.name",
                lookml_name="name",
                lookml_long_name="items_name",
                data_type="STRING",
                unique_id="test_model.items.name",
                description="Item name",
                meta=DbtModelColumnMeta()
            ),
            'items.price': DbtModelColumn(
                name="items.price",
                lookml_name="price",
                lookml_long_name="items_price", 
                data_type="FLOAT64",
                unique_id="test_model.items.price",
                description="Item price",
                meta=DbtModelColumnMeta()
            )
        },
        'meta': DbtModelColumnMeta(),
        'unique_id': "test_model",
        'resource_type': "model",
        'schema': "test_schema",
        'description': "Test model",
        'tags': []
    })
    
    view = lookml_generator._create_nested_view(model, 'test_view', array_model, 'Test View')
    assert view['name'] == 'test_view__items'
    assert view['label'] == 'Test View'
    assert 'dimensions' in view
    assert 'dimension_groups' not in view
    assert 'sets' not in view
    assert 'measures' not in view

    # Check that nested fields are properly included
    dimensions = view['dimensions']
    dimension_names = [d['name'] for d in dimensions]
    assert 'name' in dimension_names
    assert 'price' in dimension_names

def test_create_explore():
    """Test creating explore"""
    lookml_generator = LookmlGenerator()
    
    # Create test model
    model = type('TestModel', (), {
        'meta': type('Meta', (), {
            'looker': type('Looker', (), {'hidden': False})()
        })(),
        'unique_id': "test_model",
        'resource_type': "model",
        'schema': "test_schema",
        'description': "Test model",
        'tags': []
    })
    
    explore = lookml_generator._create_explore(model, 'test_view', 'Test View', {}, False)
    assert explore['name'] == 'test_view'
    assert explore['label'] == 'Test View'
    assert explore['from'] == 'test_view'
    assert explore['hidden'] == 'no'
    assert 'joins' in explore

def test_nested_array_dimension_generation():
    """Test generation of dimensions for nested array fields"""
    lookml_generator = LookmlGenerator()

    # Create a test column with a simple array type
    simple_array_column = DbtModelColumn(
        name="simple_array",
        lookml_name="simple_array",
        lookml_long_name="simple_array",
        data_type="ARRAY<INT64>",
        inner_types=["INT64"],
        unique_id="test_model.simple_array",
        meta=DbtModelColumnMeta()
    )

    # Create a test column with a complex array type
    complex_array_column = DbtModelColumn(
        name="complex_array",
        lookml_name="complex_array",
        lookml_long_name="complex_array",
        data_type="ARRAY<STRUCT<id INT64, name STRING>>",
        inner_types=["STRUCT<id INT64, name STRING>"],
        unique_id="test_model.complex_array",
        meta=DbtModelColumnMeta()
    )

    # Test dimensions in main view
    dimensions, _ = lookml_generator._lookml_dimensions_from_model(
        type('TestModel', (), {'columns': {
            'simple_array': simple_array_column,
            'complex_array': complex_array_column
        }})()
    )

    _extracted_from_test_nested_array_dimension_generation_36(
        dimensions, 'simple_array'
    )
    _extracted_from_test_nested_array_dimension_generation_36(
        dimensions, 'complex_array'
    )


# TODO Rename this here and in `test_nested_array_dimension_generation`
def _extracted_from_test_nested_array_dimension_generation_36(dimensions, arg1):
    # Check simple array dimension
    simple_array_dim = next(d for d in dimensions if d['name'] == arg1)
    assert simple_array_dim['hidden'] == 'yes'
    assert simple_array_dim['tags'] == ['array']
    assert 'type' not in simple_array_dim

def test_nested_view_dimension_generation():
    """Test generation of dimensions in nested views"""
    lookml_generator = LookmlGenerator()
    
    # Create a test column with nested struct fields
    parent_column = DbtModelColumn(
        name="items",
        lookml_name="items",
        lookml_long_name="items",
        data_type="ARRAY<STRUCT<id INT64, name STRING>>",
        inner_types=["STRUCT<id INT64, name STRING>"],
        unique_id="test_model.items",
        meta=DbtModelColumnMeta()
    )
    
    child_column = DbtModelColumn(
        name="items.id",
        lookml_name="id",
        lookml_long_name="items.id",
        data_type="INT64",
        unique_id="test_model.items.id",
        meta=DbtModelColumnMeta()
    )
    
    # Test dimensions in nested view
    dimensions, _ = lookml_generator._lookml_dimensions_from_model(
        type('TestModel', (), {'columns': {
            'items': parent_column,
            'items.id': child_column
        }})(),
        include_names=['items']
    )
    
    # Check nested field dimension
    nested_dim = next(d for d in dimensions if d['name'] == 'id')
    assert nested_dim['sql'] == 'id'  # Should use field name directly without parent prefix
    assert nested_dim['type'] == 'number'

def test_group_strings_simple_array():
    """Test grouping of simple array types"""
    lookml_generator = LookmlGenerator()
    
    # Create a simple array column
    array_column = DbtModelColumn(
        name="numbers",
        lookml_name="numbers",
        lookml_long_name="numbers",
        data_type="ARRAY<INT64>",
        inner_types=["INT64"],
        unique_id="test_model.numbers",
        meta=DbtModelColumnMeta()
    )
    
    all_columns = []
    array_columns = [array_column]
    
    structure = lookml_generator._group_strings(all_columns, array_columns)
    
    # Check structure for simple array
    assert len(structure['numbers']['children']) == 0
    assert structure['numbers']['column'] == array_column
    

def test_group_strings_nested_array():
    """Test grouping of nested array types"""
    lookml_generator = LookmlGenerator()
    
    # Create a nested array column
    parent = DbtModelColumn(
        name="items",
        lookml_name="items",
        lookml_long_name="items",
        data_type="ARRAY<STRUCT<id INT64, sub_items ARRAY<INT64>>>",
        inner_types=["STRUCT<id INT64, sub_items ARRAY<INT64>>"],
        unique_id="test_model.items",
        meta=DbtModelColumnMeta()
    )
    
    child = DbtModelColumn(
        name="items.sub_items",
        lookml_name="sub_items",
        lookml_long_name="items.sub_items",
        data_type="ARRAY<INT64>",
        inner_types=["INT64"],
        unique_id="test_model.items.sub_items",
        meta=DbtModelColumnMeta()
    )
    
    all_columns = [parent, child]
    array_columns = [parent]
    
    structure = lookml_generator._group_strings(all_columns, array_columns)
    
    print(structure)
    # Check nested structure
    assert len(structure['items']['children']) == 1
    items_struct = structure['items']['children'][0]
    assert items_struct['items.sub_items']['column'] == child
    assert len(items_struct['items.sub_items']['children']) == 0
    

def test_load_file_not_found():
    """Test handling of file not found error"""
    lookml_generator = LookmlGenerator()
    with pytest.raises(CliError, match='File not found'):
        lookml_generator._file_handler.read('nonexistent.json')

def test_write_lookml_file_with_table_name(tmp_path):
    """Test writing LookML file using table name."""
    generator = LookmlGenerator()

    # Create test model
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={},
        meta=DbtModelMeta(
            looker=DbtModelMetaLooker()
        ),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    # Test with use_table_name_as_view=True
    file_path = generator._write_lookml_file(
        output_dir=str(tmp_path),
        model=model,
        view_name="test_view",
        contents="test content",
        use_table_name_as_view=True
    )
    
    # Check file was created with table name
    assert os.path.basename(file_path) == "table_name.view.lkml"
    assert os.path.exists(file_path)
    
    with open(file_path) as f:
        assert f.read() == "test content"
    
    # Test with use_table_name_as_view=False
    file_path = generator._write_lookml_file(
        output_dir=str(tmp_path),
        model=model,
        view_name="test_view",
        contents="test content",
        use_table_name_as_view=False
    )
    
    # Check file was created with view name
    assert os.path.basename(file_path) == "test_view.view.lkml"
    assert os.path.exists(file_path)
    
    with open(file_path) as f:
        assert f.read() == "test content"

def test_lookml_view_from_dbt_model_with_table_name(tmp_path):
    """Test generating LookML view using table name."""
    generator = LookmlGenerator()

    # Create test model with array column
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={
            "array_col": DbtModelColumn(
                name="array_col",
                data_type="ARRAY",
                meta=DbtModelColumnMeta(
                    looker=DbtMetaLooker()
                )
            )
        },
        meta=DbtModelMeta(
            looker=DbtModelMetaLooker()
        ),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    # Test with use_table_name_as_view=True
    file_path = generator.lookml_view_from_dbt_model(
        model=model,
        output_dir=str(tmp_path),
        skip_explore_joins=False,
        use_table_name_as_view=True
    )
    
    # Check file was created with table name
    assert os.path.basename(file_path) == "table_name.view.lkml"
    assert os.path.exists(file_path)
    
    # Test with use_table_name_as_view=False
    file_path = generator.lookml_view_from_dbt_model(
        model=model,
        output_dir=str(tmp_path),
        skip_explore_joins=False,
        use_table_name_as_view=False
    )
    
    # Check file was created with model name
    assert os.path.basename(file_path) == "test_model.view.lkml"
    assert os.path.exists(file_path)

def test_create_nested_view_with_table_name():
    """Test creating nested view using table name."""
    generator = LookmlGenerator()

    # Create test model with array column
    model = DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={
            "array_col": DbtModelColumn(
                name="array_col",
                data_type="ARRAY",
                inner_types=["array_col.nested STRING"],
                meta=DbtModelColumnMeta(
                    looker=DbtMetaLooker()
                )
            ),
            "array_col.nested": DbtModelColumn(
                name="array_col.nested",
                data_type="STRING",
                inner_types=[],
                meta=DbtModelColumnMeta(
                    looker=DbtMetaLooker()
                )
            )
        },
        meta=DbtModelMeta(
            looker=DbtModelMetaLooker()
        ),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )
    
    array_model = model.columns["array_col"]
    
    # Test with use_table_name_as_view=True
    nested_view = generator._create_nested_view(
        model=model,
        base_name="test_base",
        array_model=array_model,
        view_label="Test View",
        use_table_name_as_view=True
    )
    
    # Check view name uses table name
    assert nested_view["name"] == "table_name__array_col"
    
    # Test with use_table_name_as_view=False
    nested_view = generator._create_nested_view(
        model=model,
        base_name="test_base",
        array_model=array_model,
        view_label="Test View",
        use_table_name_as_view=False
    )
    
    # Check view name uses base name
    assert nested_view["name"] == "test_base__array_col"

def test_lookml_dimensions_with_metadata():
    """Test dimension generation with various metadata options"""
    lookml_generator = LookmlGenerator()
    
    # Create a column with all metadata options
    column = DbtModelColumn(
        name="test_field",
        lookml_name="test_field",
        lookml_long_name="test_field",
        data_type="STRING",
        unique_id="test_model.test_field",
        is_primary_key=True,
        description="Test description",
        meta=DbtModelColumnMeta(
            looker=DbtMetaLooker(
                label="Custom Label",
                group_label="Custom Group",
                hidden=True,
                value_format_name=LookerValueFormatName.ID
            )
        )
    )
    
    dimensions, _ = lookml_generator._lookml_dimensions_from_model(
        type('TestModel', (), {'columns': {'test_field': column}})()
    )
    
    dim = dimensions[0]
    assert dim['name'] == 'test_field'
    assert dim['label'] == 'Custom Label'
    assert dim['group_label'] == 'Custom Group'
    assert dim['hidden'] == 'yes'
    assert dim['primary_key'] == 'yes'
    assert dim['value_format_name'] == 'id'
    assert dim['description'] == 'Test description'

@pytest.fixture
def mock_dbt_model():
    """Fixture for a test DBT model"""
    return DbtModel(
        name="test_model",
        path="models/test_model.sql",
        relation_name="`project.dataset.table_name`",
        columns={
            "user_id": DbtModelColumn(
                name="user_id",
                lookml_name="user_id",
                lookml_long_name="user_id",
                data_type="INT64",
                unique_id="test_model.user_id",
                meta=DbtModelColumnMeta()
            ),
            "created_at": DbtModelColumn(
                name="created_at",
                lookml_name="created_at",
                lookml_long_name="created_at",
                data_type="TIMESTAMP",
                unique_id="test_model.created_at",
                meta=DbtModelColumnMeta()
            )
        },
        meta=DbtModelMeta(),
        unique_id="test_model",
        resource_type="model",
        schema="test_schema",
        description="Test model",
        tags=[]
    )

