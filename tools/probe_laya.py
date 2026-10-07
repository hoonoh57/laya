import shutil
try:
    import torch
    cuda = torch.cuda.is_available()
    print("torch", torch.__version__, "cuda", cuda, torch.cuda.get_device_name(0) if cuda else "")
except Exception as e:
    print("torch 오류:", e)
import laya
from laya import Router
print("laya", getattr(laya, "__version__", "?"))
for n in ["predict_batch", "register", "predict_long"]:
    print(f"Router.{n:<26}", hasattr(Router, n))
for n in ["fit_abstention_thresholds", "fit_binning_map", "predict_tournament", "TrainConfig", "Agent"]:
    print(f"laya.{n:<28}", hasattr(laya, n))
for c in ["laya-train", "laya-evals", "laya-serve"]:
    print(f"{c:<33}", shutil.which(c) is not None)
