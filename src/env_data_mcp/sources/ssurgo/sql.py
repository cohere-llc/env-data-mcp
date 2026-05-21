"""SQL sanitizers, column qualifier, and query builders for the SSURGO adapter."""

from __future__ import annotations

import re

from ._client import _get_column_table_map

_RULE_NAME_RE = re.compile(r"^[A-Za-z0-9 \-\(\)\.,/&%]+$")


def _sanitize_variable(var: str) -> str:
    """Raise ValueError if *var* is not a safe SQL identifier."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var):
        raise ValueError(
            f"Invalid variable name {var!r}. "
            "Variable names must contain only letters, digits, and underscores."
        )
    return var


def _sanitize_rule_name(name: str) -> str:
    """Validate a cointerp rule name and escape single quotes for SQL."""
    if not _RULE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid rule name {name!r}. Rule names must contain only "
            "letters, digits, spaces, and common punctuation."
        )
    return name.replace("'", "''")


def _qualify(col: str) -> str:
    """Return the table-qualified form of *col* if its table is known."""
    table = _get_column_table_map().get(col)
    return f"{table}.{col}" if table else col


def _resolve_variables(variables: list[str]) -> list[str]:
    """Validate *variables* and return them."""
    for v in variables:
        _sanitize_variable(v)
    return variables


def _resolve_rule_names(rule_names: list[str]) -> list[str]:
    """Validate *rule_names* and return them."""
    for n in rule_names:
        _sanitize_rule_name(n)
    return rule_names


def _build_soil_profile_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → chorizon."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN chorizon ON chorizon.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, chorizon.hzdepb_r"""


def _build_area_summary_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → muaggatt (one aggregated row per map unit)."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN muaggatt ON muaggatt.mukey = mapunit.mukey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        ORDER BY mapunit.mukey"""


def _build_subsurface_barriers_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → corestrictions."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN corestrictions ON corestrictions.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, corestrictions.resdept_r"""


def _build_seasonal_hydrology_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → comonth → cosoilmoist."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN comonth ON comonth.cokey = component.cokey
        LEFT JOIN cosoilmoist ON cosoilmoist.comonthkey = comonth.comonthkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 comonth.comonthkey, cosoilmoist.soimoistdept_r"""


def _build_soil_suitability_sql(wkt: str, rule_names: list[str]) -> str:
    """SQL for mapunit → component → cointerp filtered by rule names."""
    safe_names = [_sanitize_rule_name(n) for n in rule_names]
    names_sql = ", ".join(f"'{n}'" for n in safe_names)
    return f"""\
        SELECT
            mapunit.mukey,
            mapunit.muname,
            component.compname,
            component.comppct_r,
            cointerp.mrulename,
            cointerp.interplrc,
            cointerp.interphr
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        JOIN cointerp ON cointerp.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        AND cointerp.mrulename IN ({names_sql})
        ORDER BY mapunit.mukey, component.cokey, cointerp.mrulename"""


def _build_ecological_site_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → coecoclass."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN coecoclass ON coecoclass.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, coecoclass.ecoclassid"""


def _build_parent_material_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → copmgrp → copm."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN copmgrp ON copmgrp.cokey = component.cokey
        LEFT JOIN copm ON copm.copmgrpkey = copmgrp.copmgrpkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 copmgrp.pmgroupname, copm.pmkind"""


def _build_soil_temperature_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → comonth → cosoiltemp."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN comonth ON comonth.cokey = component.cokey
        LEFT JOIN cosoiltemp ON cosoiltemp.comonthkey = comonth.comonthkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 comonth.comonthkey, cosoiltemp.dept_r"""
