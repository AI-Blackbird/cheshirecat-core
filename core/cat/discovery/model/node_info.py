from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class NodeInfo:
    node_id: str
    host: str
    port: int
    last_seen: datetime
    metadata: dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self):
        data = asdict(self)
        data['last_seen'] = self.last_seen.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict):
        data['last_seen'] = datetime.fromisoformat(data['last_seen'])
        return cls(**data)