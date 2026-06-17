Run a playtest session for the current UE5 project.

```bash
python scripts/ue_python.py "
import unreal
# 打开 PIE（Play In Editor）
unreal.EditorLevelLibrary.play_in_viewport()
print('PIE started')
"
```

检查 UE Output Log 中的错误。若有 crash，提取 `Saved/Logs/` 下最新日志文件并分析。
