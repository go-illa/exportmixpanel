from sqlalchemy import Column, Integer, String, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Trip(Base):
    """
    A simple model storing:
      - trip_id (unique from the ILLA system)
      - manual_distance
      - calculated_distance
      - route_quality
    You can expand as needed.
    """
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(Integer, unique=True, nullable=False)
    manual_distance = Column(Float, nullable=True)
    calculated_distance = Column(Float, nullable=True)
    route_quality = Column(String, nullable=True)
    status = Column(String, nullable=True)
    trip_time = Column(Float, nullable=True)
    completed_by = Column(String, nullable=True)
    coordinate_count = Column(Integer, nullable=True)  # New field for log count
