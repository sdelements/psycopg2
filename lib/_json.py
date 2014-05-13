"""Implementation of the JSON adaptation objects

This module exists to avoid a circular import problem: pyscopg2.extras depends
on psycopg2.extension, so I can't create the default JSON typecasters in
extensions importing register_json from extras.
"""

# psycopg/_json.py - Implementation of the JSON adaptation objects
#
# Copyright (C) 2012 Daniele Varrazzo  <daniele.varrazzo@gmail.com>
#
# psycopg2 is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# In addition, as a special exception, the copyright holders give
# permission to link this program with the OpenSSL library (or with
# modified versions of OpenSSL that use the same license as OpenSSL),
# and distribute linked combinations including the two.
#
# You must obey the GNU Lesser General Public License in all respects for
# all of the code used other than OpenSSL.
#
# psycopg2 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public
# License for more details.

import sys

from psycopg2._psycopg import ISQLQuote, QuotedString
from psycopg2._psycopg import new_type, new_array_type, register_type


# import the best json implementation available
if sys.version_info[:2] >= (2,6):
    import json
else:
    try:
        import simplejson as json
    except ImportError:
        json = None


# oids from PostgreSQL 9.2
JSON_OID = 114
JSONARRAY_OID = 199

class Json(object):
    """
    An `~psycopg2.extensions.ISQLQuote` wrapper to adapt a Python object to
    :sql:`json` data type.

    `!Json` can be used to wrap any object supported by the provided *dumps*
    function.  If none is provided, the standard :py:func:`json.dumps()` is
    used (`!simplejson` for Python < 2.6;
    `~psycopg2.extensions.ISQLQuote.getquoted()` will raise `!ImportError` if
    the module is not available).

    """
    def __init__(self, adapted, dumps=None):
        self.adapted = adapted

        if dumps is not None:
            self._dumps = dumps
        elif json is not None:
            self._dumps = json.dumps
        else:
            self._dumps = None

    def __conform__(self, proto):
        if proto is ISQLQuote:
            return self

    def dumps(self, obj):
        """Serialize *obj* in JSON format.

        The default is to call `!json.dumps()` or the *dumps* function
        provided in the constructor. You can override this method to create a
        customized JSON wrapper.
        """
        dumps = self._dumps
        if dumps is not None:
            return dumps(obj)
        else:
            raise ImportError(
                "json module not available: "
                "you should provide a dumps function")

    def getquoted(self):
        s = self.dumps(self.adapted)
        return QuotedString(s).getquoted()


def register_json(conn_or_curs=None, globally=False, loads=None,
        oid=None, array_oid=None):
    """Create and register typecasters converting :sql:`json` type to Python objects.

    :param conn_or_curs: a connection or cursor used to find the :sql:`json`
        and :sql:`json[]` oids; the typecasters are registered in a scope
        limited to this object, unless *globally* is set to `!True`. It can be
        `!None` if the oids are provided
    :param globally: if `!False` register the typecasters only on
        *conn_or_curs*, otherwise register them globally
    :param loads: the function used to parse the data into a Python object. If
        `!None` use `!json.loads()`, where `!json` is the module chosen
        according to the Python version (see above)
    :param oid: the OID of the :sql:`json` type if known; If not, it will be
        queried on *conn_or_curs*
    :param array_oid: the OID of the :sql:`json[]` array type if known;
        if not, it will be queried on *conn_or_curs*

    The connection or cursor passed to the function will be used to query the
    database and look for the OID of the :sql:`json` type. No query is
    performed if *oid* and *array_oid* are provided.  Raise
    `~psycopg2.ProgrammingError` if the type is not found.

    """
    if oid is None:
        oid, array_oid = _get_json_oids(conn_or_curs)

    JSON, JSONARRAY = _create_json_typecasters(oid, array_oid, loads)

    register_type(JSON, not globally and conn_or_curs or None)

    if JSONARRAY is not None:
        register_type(JSONARRAY, not globally and conn_or_curs or None)

    return JSON, JSONARRAY

def register_default_json(conn_or_curs=None, globally=False, loads=None):
    """
    Create and register :sql:`json` typecasters for PostgreSQL 9.2 and following.

    Since PostgreSQL 9.2 :sql:`json` is a builtin type, hence its oid is known
    and fixed. This function allows specifying a customized *loads* function
    for the default :sql:`json` type without querying the database.
    All the parameters have the same meaning of `register_json()`.
    """
    return register_json(conn_or_curs=conn_or_curs, globally=globally,
        loads=loads, oid=JSON_OID, array_oid=JSONARRAY_OID)

def _create_json_typecasters(oid, array_oid, loads=None):
    """Create typecasters for json data type."""
    if loads is None:
        if json is None:
            raise ImportError("no json module available")
        else:
            loads = json.loads

    def typecast_json(s, cur):
        if s is None:
            return None
        return loads(s)

    JSON = new_type((oid, ), 'JSON', typecast_json)
    if array_oid is not None:
        JSONARRAY = new_array_type((array_oid, ), "JSONARRAY", JSON)
    else:
        JSONARRAY = None

    return JSON, JSONARRAY

def _get_json_oids(conn_or_curs):
    # lazy imports
    from psycopg2.extensions import STATUS_IN_TRANSACTION
    from psycopg2.extras import _solve_conn_curs

    conn, curs = _solve_conn_curs(conn_or_curs)

    # Store the transaction status of the connection to revert it after use
    conn_status = conn.status

    # column typarray not available before PG 8.3
    typarray = conn.server_version >= 80300 and "typarray" or "NULL"

    # get the oid for the hstore
    curs.execute(
        "SELECT t.oid, %s FROM pg_type t WHERE t.typname = 'json';"
            % typarray)
    r = curs.fetchone()

    # revert the status of the connection as before the command
    if (conn_status != STATUS_IN_TRANSACTION and not conn.autocommit):
        conn.rollback()

    if not r:
        raise conn.ProgrammingError("json data type not found")

    return r


