from enum import Enum
from string import Template
from typing import List, Optional

from clickhouse_sqlalchemy import engines
from clickhouse_sqlalchemy.engines.base import TableCol
from sqlalchemy import func


class ReplacingMergeTree(engines.MergeTree):
    def __init__(self, *args, **kwargs):
        version_col = kwargs.pop("version", None)
        deletion_col = kwargs.pop("is_deleted", None)
        super(ReplacingMergeTree, self).__init__(*args, **kwargs)

        self.version_col = None
        if version_col is not None:
            self.version_col = TableCol(version_col)

            if deletion_col is not None:
                self.deletion_col = TableCol(deletion_col)

    def _set_parent(self, table, **kwargs):
        super(ReplacingMergeTree, self)._set_parent(table, **kwargs)

        if self.version_col is not None:
            self.version_col._set_parent(table, **kwargs)

            if self.deletion_col is not None:
                self.deletion_col._set_parent(table, **kwargs)

    def get_parameters(self):
        if self.version_col is not None:
            if self.deletion_col is not None:
                return [self.version_col.get_column(), self.deletion_col.get_column()]

            return self.version_col.get_column()

    @classmethod
    def reflect(cls, table, engine_full, **kwargs):
        engine = engines.util.parse_columns(engine_full, delimeter=" ")[0]
        columns = engine[len(cls.__name__) :].strip("()")
        # version_col = engine[len(cls.__name__):].strip('()') or None  # noqa: ERA001
        version_col, deletion_col = engines.util.parse_columns(columns)

        return cls(
            version=version_col,
            is_deleted=deletion_col,
            **cls._reflect_merge_tree(table, **kwargs),
        )


class SupportedEngines(str, Enum):
    MERGE_TREE = "MergeTree"
    REPLACING_MERGE_TREE = "ReplacingMergeTree"
    SUMMING_MERGE_TREE = "SummingMergeTree"
    AGGREGATING_MERGE_TREE = "AggregatingMergeTree"
    REPLICATED_MERGE_TREE = "ReplicatedMergeTree"
    REPLICATED_REPLACING_MERGE_TREE = "ReplicatedReplacingMergeTree"
    REPLICATED_SUMMING_MERGE_TREE = "ReplicatedSummingMergeTree"
    REPLICATED_AGGREGATING_MERGE_TREE = "ReplicatedAggregatingMergeTree"


ENGINE_MAPPING = {
    SupportedEngines.MERGE_TREE: engines.MergeTree,
    SupportedEngines.REPLACING_MERGE_TREE: ReplacingMergeTree,
    SupportedEngines.SUMMING_MERGE_TREE: engines.SummingMergeTree,
    SupportedEngines.AGGREGATING_MERGE_TREE: engines.AggregatingMergeTree,
    SupportedEngines.REPLICATED_MERGE_TREE: engines.ReplicatedMergeTree,
    SupportedEngines.REPLICATED_REPLACING_MERGE_TREE: engines.ReplicatedReplacingMergeTree,
    SupportedEngines.REPLICATED_SUMMING_MERGE_TREE: engines.ReplicatedSummingMergeTree,
    SupportedEngines.REPLICATED_AGGREGATING_MERGE_TREE: engines.ReplicatedAggregatingMergeTree,
}


def is_supported_engine(engine_type):
    return engine_type in SupportedEngines.__members__.values()


def get_engine_class(engine_type):
    return ENGINE_MAPPING.get(engine_type)


def create_engine_wrapper(
    engine_type,
    primary_keys: List[str],
    table_name: str,
    config: Optional[dict] = None,
):
    # check if engine type is in supported engines
    if is_supported_engine(engine_type) is False:
        msg = f"Engine type {engine_type} is not supported."
        raise ValueError(msg)

    engine_args: dict = {}
    if len(primary_keys) > 0:
        engine_args["primary_key"] = primary_keys
    else:
        # If no primary keys are specified,
        # then Clickhouse expects the data to be indexed on all fields via tuple().
        engine_args["order_by"] = func.tuple()

    if config is not None:
        if engine_type in (
            SupportedEngines.REPLICATED_MERGE_TREE,
            SupportedEngines.REPLICATED_REPLACING_MERGE_TREE,
            SupportedEngines.REPLICATED_SUMMING_MERGE_TREE,
            SupportedEngines.REPLICATED_AGGREGATING_MERGE_TREE,
        ):
            table_path: Optional[str] = config.get("table_path")
            if table_path is not None:
                if "$" in table_path:
                    table_path = Template(table_path).substitute(table_name=table_name)
                engine_args["table_path"] = table_path
            else:
                msg = "Table path (table_path) is not defined."
                raise ValueError(msg)
            replica_name: Optional[str] = config.get("replica_name")
            if replica_name is not None:
                engine_args["replica_name"] = replica_name
            else:
                msg = "Replica name (replica_name) is not defined."
                raise ValueError(msg)
        elif engine_type == SupportedEngines.REPLACING_MERGE_TREE:
            engine_args["version"] = "ReportDate"
            engine_args["is_deleted"] = "_is_deleted"

        engine_class = get_engine_class(engine_type)

    return engine_class(**engine_args)
