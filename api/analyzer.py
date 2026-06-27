import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationError

EXCLUDED_DIRS = {'node_modules', '.git', '__pycache__', 'vendor', 'dist', 'build', '.next', 'target'}

class ShipzenConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    builder: Optional[str] = Field(None, pattern="^(dockerfile|buildpacks|railpack|go|maven|static|auto)$")
    port: Optional[int] = Field(None, ge=1, le=65535)
    build_args: Optional[Dict[str, str]] = None
    replicas: Optional[int] = Field(None, ge=1, le=20)
    health_check_path: Optional[str] = None
    
    @field_validator('health_check_path')
    @classmethod
    def validate_health_check_path(cls, v: str) -> str:
        if v and not v.startswith('/'):
            raise ValueError("health_check_path must start with /")
        return v

@dataclass
class DetectedService:
    name: str
    path: str
    type: str
    confidence: float
    framework: Optional[str] = None
    entrypoint: Optional[str] = None
    override_config: Optional[dict] = None

class RepoAnalyzer:
    def __init__(self, repo_path: str | Path, repo_name: str | None = None):
        self.repo_path = Path(repo_path)
        self._repo_name = repo_name or self.repo_path.name

    def analyze(self) -> List[DetectedService]:
        services = []
        base_path = self.repo_path.resolve()
        
        if not base_path.exists() or not base_path.is_dir():
            return services

        def walk_path(current_path: Path):
            if current_path != base_path:
                if current_path.name in EXCLUDED_DIRS or current_path.name.startswith('.'):
                    return

            rel_path = ""
            if current_path != base_path:
                rel_path = current_path.relative_to(base_path).as_posix()

            try:
                files = {p.name for p in current_path.iterdir() if p.is_file()}
            except Exception:
                return

            override_config = None
            if 'shipzen.yaml' in files:
                try:
                    with open(current_path / 'shipzen.yaml', 'r') as f:
                        raw_cfg = yaml.safe_load(f) or {}
                    parsed = ShipzenConfig(**raw_cfg)
                    override_config = parsed.model_dump(exclude_unset=True)
                except ValidationError as e:
                    unknown_keys = [err["loc"][0] for err in e.errors() if err["type"] == "extra_forbidden"]
                    if unknown_keys:
                        raise ValueError(f"shipzen.yaml contains unknown fields: {unknown_keys}. "
                                         f"Allowed fields are: builder, port, build_args, replicas, health_check_path")
                    raise ValueError(f"shipzen.yaml validation error: {e}")
                except yaml.YAMLError as e:
                    raise ValueError(f"shipzen.yaml is not valid YAML: {e}")

            candidates = []
            
            # Dockerfile
            if 'Dockerfile' in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="dockerfile", confidence=1.0, 
                    override_config=override_config
                ))
                
            # Buildpacks (Node/Python)
            if 'package.json' in files:
                framework = None
                try:
                    content = (current_path / "package.json").read_text()
                    if '"next"' in content: framework = "nextjs"
                    elif '"vite"' in content: framework = "vite"
                    elif '"express"' in content: framework = "express"
                except:
                    pass
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="buildpacks", confidence=0.85, 
                    framework=framework, override_config=override_config
                ))
            elif any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py']):
                framework = None
                if 'manage.py' in files: framework = "django"
                req_path = current_path / "requirements.txt"
                if req_path.exists():
                    try:
                        content = req_path.read_text().lower()
                        if "fastapi" in content: framework = "fastapi"
                        elif "flask" in content: framework = "flask"
                    except:
                        pass
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="buildpacks", confidence=0.85, 
                    framework=framework, override_config=override_config
                ))
            
            # Go
            if 'go.mod' in files and 'Dockerfile' not in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="go", confidence=0.90, 
                    override_config=override_config
                ))
                
            # Java/Maven
            if 'pom.xml' in files and 'Dockerfile' not in files and 'go.mod' not in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="maven", confidence=0.88, 
                    override_config=override_config
                ))
                
            # Static HTML
            if 'index.html' in files and 'package.json' not in files and not any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py', 'go.mod', 'pom.xml']):
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="static", confidence=0.70, 
                    framework="nginx", override_config=override_config
                ))

            # Railpack (Ruby/PHP)
            if any(f in files for f in ['composer.json', 'index.php', 'Gemfile']):
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name, 
                    path=rel_path, type="railpack", confidence=0.85, 
                    override_config=override_config
                ))

            if candidates:
                # Sort descending by confidence
                candidates.sort(key=lambda x: x.confidence, reverse=True)
                best_candidate = candidates[0]
                
                if override_config and override_config.get('builder'):
                    if override_config['builder'] != 'auto':
                        best_candidate.type = override_config['builder']
                        best_candidate.confidence = 1.0
                        
                services.append(best_candidate)

            # Recurse regardless of if we found a service here — monorepos can have nested services
            try:
                for d in current_path.iterdir():
                    if d.is_dir():
                        walk_path(d)
            except Exception:
                pass

        walk_path(base_path)
        return services
