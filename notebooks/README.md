# Notebooks Workflow

This folder contains the end-to-end notebook pipeline for generating hand-landmark datasets, training gesture classifiers, and exporting TensorFlow Lite models.

## Notebook Order

1. `1.preprocessing.ipynb`
2. `2.data_analysis.ipynb`
3. `3.point_history_classification.ipynb`

## 1) `1.preprocessing.ipynb` (Image dataset -> keypoint CSV)

Purpose:

- Loads and validates the sign-language image dataset.
- Performs exploratory checks (class balance, image properties, duplicate detection).
- Extracts hand landmarks with MediaPipe Hands.
- Applies augmentation variants (flip and small rotations).
- Writes normalized landmark features to a CSV.

Inputs:

- `../data` (class-wise image folders)
- Dataset referenced in notebook: `https://www.kaggle.com/datasets/ahmedkhanak1995/sign-language-gesture-images-dataset/data`

Output:

- `../model/keypoint_classifier/keypoint2.csv`

## 2) `2.data_analysis.ipynb` (Keypoint CSV -> keypoint classifier)

Purpose:

- Loads keypoint features from `keypoint2.csv`.
- Visualizes class distribution and feature distributions.
- Applies variance-based feature filtering.
- Projects embeddings (t-SNE) for class separability checks.
- Trains a keypoint classifier (Dense network) with checkpointing and early stopping.
- Evaluates with confusion matrix/classification report.
- Converts the trained model to TFLite and runs inference checks.

Primary input:

- `../model/keypoint_classifier/keypoint2.csv`

Outputs used in the notebook:

- `../model/keypoint_classifier/keypoint_classifier.h5`
- `../model/keypoint_classifier/keypoint_classifier.tflite`

Note:

- One load step in the notebook uses `../src/letter-model-service/model/keypoint_classifier/keypoint_classifier.h5`; adjust paths in cells if your local model location differs.

## 3) `3.point_history_classification.ipynb` (Motion sequence -> point-history classifier)

Purpose:

- Trains a dynamic gesture classifier on fingertip trajectory history (16 time steps, x/y -> 32 features).
- Supports either:
  - Dense model (`use_lstm = False`), or
  - LSTM-based model (`use_lstm = True`).
- Evaluates via confusion matrix.
- Exports a quantized TFLite model and validates interpreter-based inference.

Primary input:

- `model/point_history_classifier/point_history.csv`

Outputs:

- `model/point_history_classifier/point_history_classifier.hdf5`
- `model/point_history_classifier/point_history_classifier.tflite`

## Environment

This directory includes:

- `pyproject.toml`
- `uv.lock`

From `notebooks/`, typical setup is:

```bash
uv sync
```

Then run notebooks with your preferred Jupyter environment.
