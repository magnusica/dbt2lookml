import lkml
from . import models
import logging
import os

log = logging.getLogger("rich")
class NotImplementedError(Exception):
    pass

LOOKER_BIGQUERY_DTYPE_MAP = {
    'INT64':     'number',
    'INTEGER':   'number',
    'FLOAT':     'number',
    'FLOAT64':   'number',
    'NUMERIC':   'number',
    'BIGNUMERIC': 'number',
    'BOOLEAN':   'yesno',
    'STRING':    'string',
    'TIMESTAMP': 'timestamp',
    'DATETIME':  'datetime',
    'DATE':      'date',
    'TIME':      'string',    # Can time-only be handled better in looker?
    'BOOL':      'yesno',
    'GEOGRAPHY': 'string',
    'BYTES':     'string',
    'ARRAY':     'string',
    'STRUCT':    'string'
}

LOOKER_BIGQUERY_MEASURE_TYPES = [
    'count',
    'count_distinct',
    'sum',
    'average',
    'min',
    'max',
    'median',
    'percentile',
    'percentile_approx',
    'stddev',
    'stddev_pop',
    'stddev_samp',
    'variance',
    'var_pop',
    'var_samp',
    'sum_distinct',
]

looker_date_time_types = ['datetime', 'timestamp']
looker_date_types = ['date']
looker_scalar_types = ['number', 'yesno', 'string']

looker_date_timeframes = [
    'raw', 
    'date',
    'day_of_month',
    'day_of_week',
    'day_of_week_index',
    'week',
    'week_of_year',
    'month',
    'month_num',
    'month_name', 
    'quarter',
    'quarter_of_year',
    'year'
]

looker_time_timeframes = [
    'raw', 
    'time',
    'time_of_day',
    'date', 
    'week', 
    'month', 
    'quarter', 
    'year'
]

def validate_sql(sql: str):
    ''' Validate that a string is a valid Looker SQL expression '''

    def check_if_has_dollar_syntax(sql):
        ''' check if the string either has ${TABLE}.example or ${view_name} '''
        return '${' in sql and '}' in sql
    
    def check_expression_has_ending_semicolons(sql):
        ''' check if the string ends with a semicolon '''
        return sql.strip().endswith(';;')

    if check_expression_has_ending_semicolons(sql):
        logging.warning(f"SQL expression {sql} ends with semicolons. It is removed and added by lkml.")
        sql = sql.strip().rstrip(';').rstrip(';')

    if not check_if_has_dollar_syntax(sql):
        logging.warning(f"SQL expression {sql} does not contain $TABLE or $view_name")
        return None
    else:
        return sql

def map_bigquery_to_looker(column_type: str):
    if column_type:
        column_type = column_type.split('<')[0]  # STRUCT< or ARRAY<
        column_type = column_type.split('(')[0]  # Numeric(1,31)

    looker_type = LOOKER_BIGQUERY_DTYPE_MAP.get(column_type)
    if column_type is not None and looker_type is None:
        logging.warning(f'Column type {column_type} not supported for conversion from bigquery to looker. No dimension will be created.')

    return looker_type

def lookml_dimension_group(column: models.DbtModelColumn, type: str, table_format_sql=True, model=None):
    if map_bigquery_to_looker(column.data_type) is None:
        raise NotImplementedError()
    else:
        if type == 'time':
            convert_tz = 'yes'
            timeframes = looker_time_timeframes
            column_name_adjusted = column.name.replace("_date","")
        elif type == 'date':
            convert_tz = 'no'
            timeframes = looker_date_timeframes
            column_name_adjusted = column.name.replace("_date","")
        else:
            raise NotImplementedError()
        dimensions = []
        dimension_group = {
            'name': column_name_adjusted,
            'label': column.lookml_name.replace("_date","").replace("_", " ").title(),
            'type': type,
            'sql': f'${{TABLE}}.{column.name}' if table_format_sql else f'{model.name}__{column.name}',
            'description': column.description,
            'datatype': map_bigquery_to_looker(column.data_type),
            'timeframes': timeframes,
            'group_label': f'{column.lookml_name.replace("_", " ").title()}',
            'convert_tz': convert_tz
        }
        if column.meta.looker.label != None:
            dimension_group['label'] = column.meta.looker.label
        if column.meta.looker.group_label != None:
            dimension_group['group_label'] = column.meta.looker.group_label

        dimension_group_set = {
            'name' : f's_{column_name_adjusted}',
            'fields': [
                f"{column_name_adjusted}_{looker_time_timeframe}" for looker_time_timeframe in timeframes
            ]
        }

        if type == 'date':
            iso_year = {
                'name': f'{column.name}_iso_year',
                'label': f'{column.name.replace("_date","").replace("_"," ").title()} ISO Year',
                'type': 'number',
                'sql': f'Extract(isoyear from ${{TABLE}}.{column.name})',
                'description': f'iso year for {column.name}',
                'group_label': f'{column.lookml_name.replace("_", " ").title()}',
                'value_format_name': 'id'
            }
            if column.meta.looker.group_label != None:
                iso_year['group_label'] = column.meta.looker.group_label
            if column.meta.looker.label != None:
                iso_year['label'] = f"{column.meta.looker.label} ISO Year"

            iso_week_of_year = {
                'name': f'{column.name}_iso_week_of_year',
                'label': f'{column.name.replace("_date","").replace("_"," ").title()} ISO Week Of Year',
                'type': 'number',
                'sql': f'Extract(isoweek from ${{TABLE}}.{column.name})',
                'description': f'iso year for {column.name}',
                'group_label': f'{column.lookml_name.replace("_", " ").title()}',
                'value_format_name': 'id'
            }
            if column.meta.looker.group_label != None:
                iso_week_of_year['group_label'] = column.meta.looker.group_label
            if column.meta.looker.label != None:
                iso_week_of_year['label'] = f"{column.meta.looker.label} ISO Week Of Year"

            dimensions = [iso_year, iso_week_of_year]
            dimension_group_set['fields'].extend([f"{column.name}_iso_year", f"{column.name}_iso_week_of_year"])

        if not dimensions and type=='date':
            logging.warn(f"no dimensions for {column.name} {column.data_type} {type} {table_format_sql} {model.name}__{column.name}")

        return dimension_group, dimension_group_set, dimensions


def lookml_dimension_groups_from_model(model: models.DbtModel, include_names=None, exclude_names=[]):

    dimension_groups = []
    dimension_group_sets = []
    table_format_sql = True

    for column in model.columns.values(): 

        if include_names:
            table_format_sql = False
            if column.inner_types is not None:
                if len(column.inner_types) == 1:
                    column.data_type = column.inner_types[0]
            if column.name not in include_names:
                continue
        if len(exclude_names) > 0:
            if column.name in exclude_names:
                continue

        if map_bigquery_to_looker(column.data_type) in looker_date_time_types: 
            dimension_group, dimension_set, _ = lookml_dimension_group(column, 'time', table_format_sql, model)            
        elif map_bigquery_to_looker(column.data_type) in looker_date_types:
            dimension_group, dimension_set, _ = lookml_dimension_group(column, 'date', table_format_sql, model)            
        else:
            continue

        dimension_groups.append(dimension_group)
        dimension_group_sets.append(dimension_set)

    return {'dimension_groups' : dimension_groups, 'dimension_group_sets': dimension_group_sets}


def lookml_dimensions_from_model(model: models.DbtModel, include_names=None, exclude_names=[]):
    dimensions = []
    table_format_sql = True
    is_hidden = False

    for column in model.columns.values():

        if include_names:
            table_format_sql = False

            if column.name not in include_names:
                continue

        if len(exclude_names) > 0:
            # exclude them if they are containing a dot.
            if '.' in column.name:
                if column.name in exclude_names:
                    logging.debug(f"excluding {column.name}")
                    continue

        if map_bigquery_to_looker(column.data_type) in looker_scalar_types:

            dimension = {
                'name': column.lookml_long_name if table_format_sql else column.lookml_name,
                'type': map_bigquery_to_looker(column.data_type),
                'sql': f'${{TABLE}}.{column.name}' if table_format_sql else f'{column.name.rpartition('.')[2]}',
                'description': column.description,
            }
                
            if 'ARRAY' in column.data_type :
                dimension['hidden'] = 'yes'
                dimension['tags'] = ['array']
                dimension.pop('type')

            if 'STRUCT' in column.data_type :
                dimension['hidden'] = 'yes'
                dimension['tags'] = ['struct']
                # dimension.pop('type')

            if column.is_primary_key:
                dimension['primary_key'] = 'yes'
                is_hidden = True
                dimension['value_format_name'] = 'id'

            if column.meta.looker is not None:
                if column.meta.looker.group_label != None:
                    dimension['group_label'] = column.meta.looker.group_label
                if column.meta.looker.label  != None:
                    dimension['label'] = column.meta.looker.label

                if column.meta.looker.hidden != None:
                    dimension['hidden'] = 'yes' if column.meta.looker.hidden == True else 'no'
                elif is_hidden:
                    dimension['hidden'] = 'yes'

                if column.meta.looker.value_format_name != None:
                    dimension['value_format_name'] = column.meta.looker.value_format_name.value
        
            is_hidden = False
            dimensions.append(dimension)

        if map_bigquery_to_looker(column.data_type) == 'date':
            # We need to add dimensions for date types that are not handled by dimension groups.
            # And we need to feed the lkml file with a group of dimensions
            _, _, dimension_group_dimensions = lookml_dimension_group(column, 'date', table_format_sql, model)
            if dimension_group_dimensions is None:
                logging.warning(f"no dimensions for {column.name} {column.data_type} {table_format_sql} {model.name}__{column.name}")
            else:
                dimensions.extend(dimension_group_dimensions)

    return dimensions

def lookml_measures_from_model(model: models.DbtModel, include_names=None, exclude_names=[]):
    """ Create a list of lookml measures from a dbt model.
    """
    # Initialize an empty list to hold all lookml measures.
    lookml_measures = []
    table_format_sql = True

    # Iterate over all columns in the model.
    for column in model.columns.values():
        
        if include_names:
            table_format_sql = False
            if column.name not in include_names:
                continue
        if len(exclude_names) > 0:

            if column.name in exclude_names:
                continue

        if map_bigquery_to_looker(column.data_type) in looker_scalar_types:

            if hasattr(column.meta, 'looker_measures'):
                # For each measure found in the combined dictionary, create a lookml_measure.
                for measure in column.meta.looker_measures:
                    # Call the lookml_measure function and append the result to the list.
                    lookml_measures.append(lookml_measure(column, measure, table_format_sql, model))

    # Return the list of lookml measures.
    return lookml_measures

def lookml_measure(column: models.DbtModelColumn, measure: models.DbtMetaMeasure, table_format_sql, model):
    
    if measure.type.value not in LOOKER_BIGQUERY_MEASURE_TYPES:
        logging.warning(f"Measure type {measure.type.value} not supported for conversion to looker. No measure will be created.")
        return None
    
    m = {
        'name': f'm_{measure.type.value}_{column.name}',
        'type': measure.type.value,
        'sql':  f'${{{column.name}}}' if table_format_sql else f'${{{model.name}__{column.name}}}',
        'description': f'{measure.type.value} of {column.name}',
    }

    # inherit the value format, or overwrite it
    if measure.value_format_name != None:
        m['value_format_name'] = measure.value_format_name.value
    elif column.meta.looker != None:
        if column.meta.looker.value_format_name != None:
            m['value_format_name'] = column.meta.looker.value_format_name.value        

    # allow configuring advanced lookml measures
    if measure.sql != None:
        validated_sql = validate_sql(measure.sql)
        if validated_sql is not None:
            m['sql'] = validated_sql
            if measure.type.value != 'number':
                logging.warn(f"SQL expression {measure.sql} is not a number type measure. It is overwritten to be number since SQL is set.")
                m['type'] = 'number'
    
    if measure.sql_distinct_key != None:
        validated_sql = validate_sql(measure.sql_distinct_key)
        if validated_sql is not None:
            m['sql_distinct_key'] = validated_sql
        else:
            logging.warn(f"SQL expression {measure.sql_distinct_key} is not valid. It is not set as sql_distinct_key.")

    if measure.approximate != None:
        m['approximate'] = measure.approximate
    
    if measure.approximate_threshold != None:
        m['approximate_threshold'] = measure.approximate_threshold
    
    if measure.allow_approximate_optimization != None:
        m['allow_approximate_optimization'] = measure.allow_approximate_optimization
    
    if measure.can_filter != None:
        m['can_filter'] = measure.can_filter

    if measure.tags != None:
        m['tags'] = measure.tags

    if measure.alias != None:
        m['alias'] = measure.alias
    
    if measure.convert_tz != None:
        m['convert_tz'] = measure.convert_tz

    if measure.suggestable != None:
        m['suggestable'] = measure.suggestable

    if measure.precision != None:
        m['precision'] = measure.precision

    if measure.percentile != None:
        m['percentile'] = measure.percentile

    if measure.group_label != None:
        m['group_label'] = measure.group_label

    if measure.label != None:
        m['label'] = measure.label

    if measure.hidden != None:
        m['hidden'] = measure.hidden.value

    if measure.description != None:
        m['description'] = measure.description

    logging.debug(f"measure created: {m}" )
    return m


def extract_array_models(columns: list[models.DbtModelColumn])->list[models.DbtModelColumn]:
    ''' Process columns to determine if they are nested 
        and if so, what the parent group is
    '''
    array_list = []

    # Initialize parent_list with all columns that are arrays
    for column in columns:
        if column.data_type is not None:
            if 'ARRAY' == column.data_type:
                array_list.append(column)
                
    return array_list


def group_strings(all_columns:list[models.DbtModelColumn], array_columns:list[models.DbtModelColumn]):
    nested_columns = {}

    def remove_parts(input_string):
        parts = input_string.split('.')
        modified_parts = parts[:-1]
        result = '.'.join(modified_parts)
        return result
    
    def recurse(parent: models.DbtModelColumn, all_columns:list[models.DbtModelColumn], level = 0):
        structure = {
            'column' : parent,
            'children' : []
        }

        logging.debug(f"level {level}, {parent.name}")
        for column in all_columns:
            # singleton array handling
            if column.name == parent.name:
                logging.debug('has identical name %s %s', column.name, parent.name)
                if len(column.inner_types) == 1:
                    structure['children'].append({column.name : {'column' : column, 'children' : []}})

            # descendant handling
            if remove_parts(column.name) == parent.name:
                logging.debug(f"column {column.name} ({remove_parts(column.name)}) is a direct descendant of {parent.name}")
                structure['children'].append({column.name : recurse(
                            parent = column,
                            all_columns = [d for d in all_columns if remove_parts(d.name) == column.name],
                            level=level+1)})   
            # inner_types handling
            elif column.name in parent.inner_types:
                logging.debug(f"column {column.name} is a nested child of {parent.name}")
                structure['children'].append({column.name : recurse(
                            parent = column,
                            all_columns = [d for d in all_columns if remove_parts(d.name) == column.name],
                            level=level+1)})

        return structure
    
    for parent in array_columns:
        nested_columns[parent.name] = recurse(parent, all_columns)
        logging.debug('nested_parent: %s', parent.name)

    return nested_columns

def lookml_view_from_dbt_model(model: models.DbtModel, output_dir: str, skip_explore_joins: False, use_table_name_as_view=False):
    ''' Create a looker view from a dbt model 
        if the model has nested arrays, create a view for each array
        and an explore that joins them together
    '''
    def recurse_views(structure, level=0):
        view_list = []
        used_names = []
        
        for parent, children in structure.items():
            children_names = []
            #logging.info(f"{children['children']})")
            for child_strucure in children['children']:
                for child_name, child_dict in child_strucure.items():
                    children_names.append(child_name)
                    if len((child_dict['children'])) > 0:
                        recursed_view_list, recursed_names = recurse_views(child_strucure, level=level+1)
                        view_list.extend(recursed_view_list)
                        used_names.extend(recursed_names)
            logging.info(f"adding view for {parent} on level {level}")
            logging.debug(f"children names: {children_names}")
            #logging.debug(f"children {lookml_dimensions_from_model(model, include_names=children_names)}")
            
            view_name = model.name + "__" + parent.replace('.','__')
            if use_table_name_as_view:
                view_name = model.relation_name.split('.')[-1].strip('`') + "__" + parent.replace('.','__')
                logging.info('skipping appending model name for %s', view_name)

            view_list.append(
                {
                    'name': view_name,
                    'label': view_label,
                    'dimensions': lookml_dimensions_from_model(model, include_names=children_names),
                    'dimension_groups': lookml_dimension_groups_from_model(model, include_names=children_names).get('dimension_groups'),
                    'sets' : lookml_dimension_groups_from_model(model, include_names=children_names).get('dimension_group_sets'),
                    'measures': lookml_measures_from_model(model, include_names=children_names),
                }
            )
            used_names.extend(children_names)
        return view_list, used_names

    def rael(input_string):
        ''' replace all but the last period with a replacement string 
            this is used to create unique names for joins
        '''
        sign = '.'
        replacement = '__'
        
        # Splitting input_string into parts separated by sign (period)
        parts = input_string.split(sign)
        
        # If there's more than one part, we need to do replacements.
        if len(parts) > 1:
            # Joining all parts except for last with replacement,
            # and then adding back on final part.
            output_string = replacement.join(parts[:-1]) + sign + parts[-1]
            
            return output_string
        
        # If there are no signs at all or just one part,
        return input_string

    def recurse_joins(structure):
        join_list = []
        for parent, children in structure.items():
            for child_strucure in children['children']:
                for _, child_dict in child_strucure.items():
                    if len((child_dict['children'])) > 0:
                        recursed_join_list = recurse_joins(child_strucure)
                        join_list.extend(recursed_join_list)
            
            join_name = rael(model.name+"."+parent)
            name = model.name
            if use_table_name_as_view:
                name = model.relation_name.split('.')[-1].strip('`')
                join_name = rael(name+"."+parent)
                        
            join_list.append(
                {
                    'sql' : f'LEFT JOIN UNNEST(${{{rael(join_name)}}}) AS {model.name}__{parent.replace(".","__")}',
                    'relationship': 'one_to_many',
                    'name': name + "__" + parent.replace('.','__'),
                }
            )
        return join_list
    
    
    logging.info(f"starting processing of {model.name}")
    array_models = extract_array_models(model.columns.values())
    structure = group_strings(model.columns.values(), array_models)
    lookml = {}
    lookml_list = []

    view_label = None
    # Add 'label' only if it exists
    if hasattr(model.meta.looker, 'label'):
        if model.meta.looker.label is not None:
            view_label = model.meta.looker.label
        elif hasattr(model, 'name'):
            view_label = model.name.replace("_", " ").title()
    elif hasattr(model, 'name'):
        view_label = model.name.replace("_", " ").title()

    if view_label is None:
        logging.warning(f"This model has no name: {model.name}")

    # this is for handling arrays
    used_names = []
    if structure:
        view_list, used_names = recurse_views(structure, 0)
        logging.debug(used_names)
        logging.debug(view_list)
        lookml_list.append(view_list)

    model_dimensions = lookml_dimensions_from_model(model, exclude_names=used_names)
    
    if len(model_dimensions) == 0:
        return None
    
    view_name = model.name
    if use_table_name_as_view:
        view_name = model.relation_name.split('.')[-1].strip('`')
        logging.info('skipping appending model name for %s', view_name)
    
    lookml_view = [
        {
            'name': view_name,
            'label': view_label,
            'sql_table_name': model.relation_name,
            'dimensions': model_dimensions,
            'dimension_groups': lookml_dimension_groups_from_model(model, exclude_names=used_names).get('dimension_groups'),
            'sets' : lookml_dimension_groups_from_model(model, exclude_names=used_names).get('dimension_group_sets'),
            'measures': lookml_measures_from_model(model, exclude_names=used_names),
        }
    ]

    lookml_list.append(lookml_view)

    if len(array_models) > 0:
        logging.info(f"{view_name} explore view definition")

        hidden = 'yes'
        if hasattr(model.meta.looker, 'hidden'):
            hidden = model.meta.looker.hidden
            
        if skip_explore_joins is False:
            lookml_explore = [
            {
                'name': view_name, # to avoid name conflicts
                'label': view_label,
                'joins': [],
                'hidden': hidden
            }
            ]
            lookml_explore[0]['joins'].extend(recurse_joins(structure))
            lookml = {
                'explore': lookml_explore,
                'view': list(reversed(lookml_list)),
            }
        else:
            logging.info(f"Skipping explore joins")
            lookml = {
                'view': list(reversed(lookml_list)),
            }          
    else:
        logging.info(f"{model.name} single view definition")
        lookml = {
            'view': list(reversed(lookml_list)),
        }

    try: 
        contents = lkml.dump(lookml)
        model_failed = False
    except TypeError as e:
        logging.error(f"Error in this model: {model.name} TYPEERROR when dumping lookml: {e}")
        model_failed = True

    if model_failed:
        return None
    else:
        path = os.path.join(output_dir, model.path.split(model.name)[0])
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            
        path = f'{path}/{view_name}.view.lkml'
        
        with open(path, 'w') as f:
            f.truncate()
            f.write(contents)
        
        logging.debug(f'Generated {path}')
        return path
