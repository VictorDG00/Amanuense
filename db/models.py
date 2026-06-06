from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class CorpusDocument(Base):
    __tablename__ = "corpus_documents"

    id = Column(String, primary_key=True)
    authority = Column(String, nullable=False, default="BCB")
    type = Column(String, nullable=False, default="resolucao")
    number = Column(String, nullable=True)
    year = Column(Integer, nullable=False)
    data_publicacao = Column(String, nullable=False)
    data_vigor = Column(String, nullable=False)
    vigency_status = Column(String, nullable=False, default="vigente")
    description = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_registry_dict(self) -> dict:
        return {
            "authority": self.authority,
            "type": self.type,
            "number": self.number,
            "year": self.year,
            "dataPublicacao": self.data_publicacao,
            "dataVigor": self.data_vigor,
            "vigencyStatus": self.vigency_status,
            "description": self.description,
        }


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
