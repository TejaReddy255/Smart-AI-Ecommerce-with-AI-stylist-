from pathlib import Path
import numpy as np
import pandas as pd 
import faiss, torch, open_clip
from PIL import Image

DATA_DIR = Path("data")
IMG_DIR = DATA_DIR/ "images"
CSV_Path = DATA_DIR/ "styles.csv"

EMB_DIR = Path("embeddings"); EMB_DIR.mkdir(parents=True,exist_ok=True)
IDX_DIR = Path("indexes"); IDX_DIR.mkdir(parents=True,exist_ok=True)

EMB_FILE = EMB_DIR/"clip_image_vectors.npy"
IDX_FILE = EMB_DIR/"ids.npy"
FAISS_FILE = IDX_DIR/ "faiss_clip.index"

MODEL_NAME = "ViT-B-32"
PRETRAINED = "openai"
DEVICE = "cpu"

def build_index():
    df = pd.read_csv(CSV_Path)

    items=[]
    for _,row in df.iterrows():
        pid = str(row["id"])
        path = IMG_DIR/ f"{pid}.jpg"
        if path.exists():
            items.append((pid,path))

    model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained = PRETRAINED, device= DEVICE)
    model.eval()

    ids, feats = [], []
    for pid, img_path in items:
        try:
            with Image.open(img_path).convert("RGB") as im:
                im_t = preprocess(im).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    feat = model.encode_image(im_t)
                    feat = feat/ feat.norm(dim=-1, keepdim=True)
            feats.append(feat.cpu().numpy().astype("float32"))
            ids.append(pid)
        except Exception as e:
            print(f"[WARN] Skipping {img_path.name}: {e}")

    feats = np.concatenate(feats,axis=0).astype("float32")
    np.save(EMB_FILE,feats)
    np.save(IDX_FILE, np.array(ids,dtype=object))

    index = faiss.IndexFlatIP(feats.shape[1])
    index.add(feats)
    faiss.write_index(index,str(FAISS_FILE))

    print(f"[OK] Build index with {len(ids)} .jpg images -> {FAISS_FILE}")


if __name__ == "__main__":
    build_index()