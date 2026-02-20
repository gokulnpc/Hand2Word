#!/usr/bin/env python
# -*- coding: utf-8 -*-
import numpy as np
import tensorflow as tf


class KeyPointClassifier(object):
    def __init__(
        self,
        model_path='model/keypoint_classifier/keypoint_classifier.tflite',
        num_threads=1,
    ):
        self.interpreter = tf.lite.Interpreter(model_path=model_path,
                                               num_threads=num_threads)

        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

    def __call__(
        self,
        landmark_list,
    ):
        """
        Args:
            landmark_list: list of 21 landmark points (x, y), length 42
        Returns:
            tuple: (result_index, confidence_score)
                - result_index: index of the predicted class
                - confidence_score: probability/confidence of the prediction (0-1)
        """
        # Keep only features 3 to 42 (i.e., index 2 to 41 in Python)
        landmark_input = landmark_list[2:]

        input_details_tensor_index = self.input_details[0]['index']
        self.interpreter.set_tensor(
            input_details_tensor_index,
            np.array([landmark_input], dtype=np.float32))
        self.interpreter.invoke()

        output_details_tensor_index = self.output_details[0]['index']

        result = self.interpreter.get_tensor(output_details_tensor_index)
        
        # Get probabilities for all classes
        probabilities = np.squeeze(result)
        
        # Get the predicted class index and its confidence
        result_index = np.argmax(probabilities)
        confidence_score = float(probabilities[result_index])

        return result_index, confidence_score
