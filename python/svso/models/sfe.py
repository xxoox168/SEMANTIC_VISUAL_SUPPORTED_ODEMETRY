"""
Author: LEI WANG (yiak.wy@gmail.com)
Date: March 1, 2020
Updated: April 1, 2020
"""

import os
import sys
import random
import math
import numpy as np
import pandas as pd
import skimage.io
import matplotlib
import matplotlib.pyplot as plt

import logging

_logger = logging.getLogger("sfe")

try:
    add_path
except NameError:
    def add_path(path):
        path = os.path.abspath(path)
        if path not in sys.path:
            logging.info("loading path %s ..." % path)
            sys.path.insert(0, path)
        else:
            logging.info("path %s exists!" % path)

pwd = os.path.dirname(os.path.realpath(__file__))
add_path(os.path.join(pwd, '..', 'config'))
# add_path(os.path.join(pwd, '../../../', 'build/proto_codec'))

from config import Settings
from svso.lib.log import LoggerAdaptor
# legacy code
# from svso.system_tracker.tracker import Pixel2D
from svso.py_pose_graph.frame import Pixel2D

# basic data structure

class SFEConfig(Settings):
    pass

sfe_config = SFEConfig("svso.models.settings")
add_path(sfe_config.MRCNN)
add_path(sfe_config.MRCNN_COCO_DATASET)

# Our GPU does not have enough memory to run the model
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import tensorflow as tf
print("tensorflow ver: ", tf.__version__)

import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()

# Our GPU does not have enough memory to run the model
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# disable console message output
tf.logging.set_verbosity(tf.logging.ERROR)

# use cpu only
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

from mrcnn import utils
import mrcnn.model as Model
import coco

def is_tf_1():
    import tensorflow
    return tensorflow.__version__.startswith('1.')

def config_cpu_device():
    tf_config = tf.ConfigProto(device_count={'CPU': 1, 'GPU': 0})

    GPU_FRACTION = 0.5
    # config.gpu_options.per_process_gpu_memory_fraction = GPU_FRACTION
    # K.tensorflow_backend.set_session(tf.Session(config=config))

    # see issues raised from https://github.com/tensorflow/issues/24496
    # tf_config.log_device_placement = True
    tf_config.gpu_options.allow_growth = True
    tf_config.gpu_options.per_process_gpu_memory_fraction = GPU_FRACTION
    tf.keras.backend.set_session(tf.Session(config=tf_config))

    return

def config_gpu_device():
    tf_config = tf.ConfigProto()

    GPU_FRACTION = 0.5
    # config.gpu_options.per_process_gpu_memory_fraction = GPU_FRACTION
    # K.tensorflow_backend.set_session(tf.Session(config=config))

    # see issues raised from https://github.com/tensorflow/issues/24496
    # tf_config.log_device_placement = True
    tf_config.gpu_options.allow_growth = True
    tf_config.gpu_options.per_process_gpu_memory_fraction = GPU_FRACTION
    tf.keras.backend.set_session(tf.Session(config=tf_config))

    # another approach
    gpus = tf.config.experimental.list_physical_devices('GPU')
    if gpus:
        try:
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError as e:
            print(e)

    return

config_cpu_device()

import keras
import keras.backend as K
import keras.layers as KL
import keras.engine as KE
import keras.models as KM

# opencv format
K.set_image_data_format('channels_last')

# Attention!
# mocked, we will transfer the definition into dataset.py, where we implemented {DATA_SOURCE_NAME}Dataset for different
# data sources
class Dataset:

    def __init__(self, name, datapath, mode):
        self._name = name
        self._class_names = []
        # a Datapath instance
        self._data_path = datapath
        self._mode = mode
        self._dataset_meta = {}
        self._images_info = []

        # used for data augumentation
        self._augumented = True
        # set True when dealing with a synthetic dataset
        self._datagen = False

    def set_datagen(self, datagen):
        self._datagen = datagen

    # interface to be implemented by subclass
    def augument_data(self, data):
        raise Exception("Not Implemented!")

    @property
    def name(self):
        return self._name

    @property
    def class_names(self):
        return self._class_names

    @property
    def images_info(self):
        return self._images_info

    @property
    def data_path(self):
        return self._data_path

    def add_class(self, kls):
        raise Exception("Not Implemented!")

    def add_image(self, source, image_id, path, **kwargs):
        image_info = {
            "source": source,
            "id": id,
            "path": path
        }
        image_info.update(kwargs)
        self._images_info.append(image_info)
        return self

# see my examples how to use coco dataset and cocoApi in https://aistudio.baidu.com/aistudio/projectdetail/60968
class CocoDataset(Dataset):

    def __init__(self, name="coco", datapath=None, mode='infer'):
        Dataset.__init__(self, name, datapath, mode)

        #
        self._class_names = [
            'BG', 'person', 'bicycle', 'car', 'motorcycle', 'airplane',
            'bus', 'train', 'truck', 'boat', 'traffic light',
            'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird',
            'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear',
            'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie',
            'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
            'kite', 'baseball bat', 'baseball glove', 'skateboard',
            'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
            'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
            'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza',
            'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
            'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote',
            'keyboard', 'cell phone', 'microwave', 'oven', 'toaster',
            'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors',
            'teddy bear', 'hair drier', 'toothbrush'
        ]


class SemanticFeatureExtractor:
    """
    Author: LEI WANG (yiak.wy@gmail.com)
    Date: March 1, 2020

    """

    logger = LoggerAdaptor("SemanticFeatureExtractor", _logger)

    # shared encoder among all SemanticFeatureExtractor instances
    label_encoder = None
    _base_model = None
    _model = None

    def __init__(self, base_model=None, config=None):
        self._config = config or sfe_config
        self._base_model = base_model or self.get_base_model()

        # input tensor to the model
        self.inp = None

        # output feature tensor
        self.features = None

        # FPN feature maps
        self.feature_maps = None

        # pool_size
        self.POOL_SIZE = self._base_model.config.POOL_SIZE

        # weak ref to frame attached to
        self._frame = None

        self.dataset = CocoDataset()

        # dataset helpers
        self.LABELS_SET = self.dataset.class_names

        # pool channel
        self.POOL_CHANNEL = None

        # key points control
        # due to our experiment report, we will no longer use bbox as keypoints
        self.USE_BBOX_AS_KEY_POINTS = False

        # key points type
        self.USE_ROI_LEVEL_ORB = True

        # Score threshold to exclude the detection result
        self.thr = 0.85

        # choosed subset of detection labels
        self.TRACK_LABELS_SET = [
            'BG', 'person',
            # 'bicycle', 'car', 'motorcycle', 'airplane','bus', 'train', 'truck', 'boat', 'traffic light',
            'cat', 'dog',
            'backpack', 'umbrella', 'handbag', 'tie', 'suitcase',
            'sports ball',
            # 'kite',
            'bottle', 'wine glass', 'cup',
            'fork', 'knife', 'spoon', 'bowl',
            'banana', 'apple',
            'sandwich', 'hot dog', 'pizza', 'donut', 'cake',
            'orange', 'broccoli', 'carrot',
            'chair', 'couch',
            'potted plant',
            'bed', 'dining table', 'toilet', 'tv', 'laptop',
            'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster',
            'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors',
            'teddy bear', 'hair drier', 'toothbrush'
        ]

        self._model = self.get_model()

    def attach_to(self, frame):
        self._frame = frame
        return self

    def get_base_model(self):
        if SemanticFeatureExtractor._base_model is None:
            config = self._config
            if not os.path.exists(config.COCO_MODEL_PATH):
                utils.download_trained_weights(config.COCO_MODEL_PATH)
            # build mrcnn model
            class InferenceConfig(coco.CocoConfig):
                # Set batch size to 1 since we'll be running inference on
                # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
                GPU_COUNT = 1
                IMAGES_PER_GPU = 1

            mrcnn_config = InferenceConfig()
            # config_cpu_device()
            # Create model object in inference mode.
            base_model = Model.MaskRCNN(mode="inference", model_dir=config.MODEL_PATH, config=mrcnn_config)

            # Load weights trained on MS-COOO
            base_model.load_weights(config.COCO_MODEL_PATH, by_name=True)

            SemanticFeatureExtractor._base_model = base_model

            def initKerasModel(model):
                for layer in model.layers:
                    layer.trainable = False
                return model

            self._base_model.keras_model = initKerasModel(self._base_model.keras_model)
        return self._base_model

    def get_model(self):
        model = SemanticFeatureExtractor._model
        if model is None:
            # restructure the model
            base_model = self.get_base_model()

            # see Keras implementation of MaskRCNN for inference mode

            # MaskRCNN accepts input image, generated
            self.inp = base_model.keras_model.inputs

            # @todo : TODO important!

            # RPN compute (dx, dy, log(dh), log(dw)) and ProposalLayer generates filtered bbox
            # of ROIs with topK and Non-Maximal-Suppression algorithms. Then ROIAlign layer aligns ROI with
            # Pyramid Network Features (generarted in the last step).
            #
            #  x = PyramidROIAlign([pool_size, pool_size], name="{Task_Name}")([rois, image_meta] + fpn_feature_maps)
            #
            # Features vector shape : (batch, size of diferent ratios, vectorized image cropped by bbox(using interpolation algorihtms), )
            # Note MaskRCNN only implements resized 244*244 F:RoI -> FPN mapping F (sampling pixels to the level of feature map) and
            # roi level for Pyramid Network head is computed using
            #
            #   RoI_level = Tensor.round(4+log2(sqrt(w*h)/(244/sqrt(IMAGE_WIDTH x IMAGE_HEIGHT))))
            #
            # Where w and h are the size of RoI. Note most of 'famous' implementation just "crop and resize by binlinar interpolation".
            # You don't know how a "statement" is implemented until you see it (feel sad)
            #
            from mrcnn.model import PyramidROIAlign, norm_boxes_graph

            config = self._base_model.config
            inputs = self.inp

            input_image = inputs[0]
            image_meta = inputs[1]
            rois_inp = KL.Input(shape=[None, 4], name="rois_inp")
            rois_inp1 = KL.Lambda(lambda x: norm_boxes_graph(x, K.shape(input_image)[1:3]))(rois_inp)

            feature_maps = self.feature_maps
            if feature_maps is None:
                P2 = self._base_model.keras_model.get_layer('fpn_p2').output
                P3 = self._base_model.keras_model.get_layer('fpn_p3').output
                P4 = self._base_model.keras_model.get_layer('fpn_p4').output
                P5 = self._base_model.keras_model.get_layer('fpn_p5').output
                feature_maps = [P2, P3, P4, P5]
                self.feature_maps = feature_maps

            x = PyramidROIAlign((config.POOL_SIZE, config.POOL_SIZE), name="features_extractor")(
                [rois_inp1, image_meta] + feature_maps)
            self.features = x

            self.logger.info("Constructing deep feature extration model ...")

            class ModelWrapper:

                def __init__(self, keras_model, base_model):
                    self._keras_model = keras_model
                    self._base_model = base_model

                def detect(self, img, bboxes):
                    # mold images
                    molded_images, image_metas, windows = self._base_model.mold_inputs([img])

                    # get anchors
                    config = self._base_model.config
                    anchors = self._base_model.get_anchors(molded_images[0].shape)
                    anchors = np.broadcast_to(anchors, (config.BATCH_SIZE,) + anchors.shape)

                    # reshape bbox
                    bboxes = np.broadcast_to(bboxes, (config.BATCH_SIZE,) + bboxes.shape)

                    features = self._keras_model.predict([bboxes, molded_images, image_metas, anchors], verbose=0)
                    return features

            model = ModelWrapper(
                KM.Model(inputs=[rois_inp, ] + inputs, outputs=self.features, name="SemanticFeatureExtractor"),
                self._base_model)
            SemanticFeatureExtractor._model = model
            self.logger.info("Construction of deep feature extraction model complete.")
        return model

    def encodeDeepFeatures(self, boxes, masks, roi_features, class_ids, scores):
        keypoints = []
        features = []

        n_instances = boxes.shape[0]
        for i in range(n_instances):
            keypoints_per_box = []
            feature = {}

            if not np.any(boxes[i]):
                # Skip this instance. Has no bbox. Likely lost in image cropping.
                continue

            y1, x1, y2, x2 = boxes[i]

            class_id = class_ids[i]
            score = scores[i]
            label = self.LABELS_SET[class_id]

            # our landmark idx starts from 1
            print("#%d type(%s), score:%f, bbox:" % (i + 1, label, score), (x1, y1, x2, y2))

            if label not in self.TRACK_LABELS_SET:
                # self.logger.info("Found label unexpected label %s for track, ignore ..." % label)
                print("Found label unexpected label %s for track, ignore ..." % label)
                continue

            if score < self.thr:
                print("detected %s score is less than %f, ignore ..." % (label, self.thr) )
                continue

            if self.USE_BBOX_AS_KEY_POINTS:
                keypoints_per_box.append(Pixel2D(y1, x1).set_frame(self._frame))
                keypoints_per_box.append(Pixel2D(y1, x1).set_frame(self._frame))

            if self.USE_ROI_LEVEL_ORB:
                kp, des = self._frame.ExtractORB(bbox=boxes[i], label=label)
                for j, p in enumerate(kp):
                    # kp coordiantes are float numbers
                    # assert (p.pt[1] - int(p.pt[1])) != 0
                    # assert (p.pt[0] - int(p.pt[0])) != 0
                    keypoints_per_box.append(
                        Pixel2D(p.pt[1], p.pt[0]).set_frame(self._frame).set_kp(p).set_feature(des[j]))

                # keep a referene to key points associated with the descriptor
                feature['roi_orb'] = (des, kp)

                self.logger.info("extracting orb key points and features for detection")

            feature['box'] = boxes[i]
            feature['mask'] = masks[:, :, i]

            # for vocabulary database of large size, please use one-hot encoding + embedding instead.
            # encode it to category value vector
            if SemanticFeatureExtractor.label_encoder is None:
                from sklearn.preprocessing import LabelEncoder
                from sklearn.preprocessing import OneHotEncoder

                label_encoder = LabelEncoder()
                indice = label_encoder.fit_transform(self.TRACK_LABELS_SET)
                categorical_features_encoder = OneHotEncoder(handle_unknown='ignore')

                inp = list(zip(self.TRACK_LABELS_SET, indice))
                print("categorical_features shp:", np.array(inp).shape)
                import pandas as pd
                df = pd.DataFrame({
                    'LABEL': self.TRACK_LABELS_SET,
                    'int': indice
                })
                print(df.head(10))
                categorical_features_encoder.fit(inp)
                encoded_features = categorical_features_encoder.transform(inp).toarray()

                def encoder(label):
                    new_class_id = self.TRACK_LABELS_SET.index(label)
                    return encoded_features[new_class_id, :]

                SemanticFeatureExtractor.label_encoder = encoder

            feature['roi_feature'] = roi_features[i]
            feature['class_id'] = SemanticFeatureExtractor.label_encoder(label)
            feature['score'] = score
            # feature['keypoints_per_box'] = keypoints_per_box

            # used for constructin of observation
            feature['label'] = label

            # add to features list
            features.append(feature)
            keypoints.append(keypoints_per_box)

        return (keypoints, features)

    def detect(self, img):
        base_model = self.get_base_model()
        ret = base_model.detect([img], verbose=1)[0]
        return ret

    def compute(self, img, detection):
        # get keras model
        model = self.get_model()

        # BATCH_SIZE is set to 1
        roi_features = model.detect(img, detection['rois'])[0]
        print("roi_features shape: ", roi_features.shape)

        rois, masks = detection['rois'], detection['masks']
        assert (len(rois) == roi_features.shape[0])
        assert (self.POOL_SIZE == roi_features.shape[1] == roi_features.shape[2])

        self.POOL_CHANNEL = roi_features.shape[3]
        shp = roi_features.shape
        roi_features = np.reshape(roi_features, (shp[0], shp[1] * shp[2] * shp[3]))

        print("=== Detection Results ===")

        keypoints, features = self.encodeDeepFeatures(rois, masks, roi_features, detection['class_ids'],
                                                      detection['scores'])
        return (keypoints, features)


def save_sfe_to_serving(model, export_path):
    if os.path.isdir(export_path):
        logging.info("%s already exits, deleting it ...")
        os.system("rm -rf %s" % export_path)
    # see tensorflow.org/api_docs/python/tf/compat/v1/saved_model/Builder
    try:
        builder = tf.save_model.builder.SavedModelBuilder(export_path)
    except:
        # Tensorflow 2.2.0-rc
        builder = tf.saved_model.builder.SavedModelBuilder(export_path)
    signature = tf.saved_model.signature_def_utils.predict_signature_def(
        # bboxes, molded_images, image_metas, anchors
        inputs={
            'bboxes': model.inputs[0],
            'molded_images': model.inputs[1],
            'image_metas': model.inputs[2],
            'anchors': model.inputs[3]},
        outputs={
            'feature': model.outputs[0]
        }
    )

    legacy_op = tf.group(tf.tables_initializer(), name='legacy_init_op')

    if is_tf_1():
        Session = K.get_session
    else:
        # tensorflow 2.2.0-rc has depreacted suppport of Keras.get_session
        Session = tf.Session

    with Session(graph=tf.Graph()) as sess:
        builder.add_meta_graph_and_variables(
            sess=sess,
            tags=[tf.saved_model.tag_constants.SERVING],
            signature_def_map={
                tf.saved_model.signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY: signature
            },
            legacy_init_op=legacy_op
        )
        builder.save()

def save_mrcnn_to_serving(model, export_path):
    if os.path.isdir(export_path):
        logging.info("%s already exits, deleting it ...")
        os.system("rm -rf %s" % export_path)
    try:
        builder = tf.save_model.builder.SavedModelBuilder(export_path)
    except:
        # Tensorflow 2.2.0-rc
        builder = tf.saved_model.builder.SavedModelBuilder(export_path)
    signature = tf.saved_model.signature_def_utils.predict_signature_def(
        # bboxes, molded_images, image_metas, anchors
        inputs={
            'input_image': model.inputs[0],
            'input_image_meta': model.inputs[1],
            'input_anchors': model.inputs[2]},
        outputs={
            'detections': model.outputs[0], # important!
            'class': model.outputs[1],
            'bbox': model.outputs[2],
            'mask': model.outputs[3], # important!
            'rpn_rois': model.outputs[4],
            'rpn_class': model.outputs[5],
            'rpn_bbox': model.outputs[6]
        }
    )

    legacy_op = tf.group(tf.tables_initializer(), name='legacy_init_op')

    if is_tf_1():
        Session = K.get_session
    else:
        Session = tf.Session

    with Session(graph=tf.Graph()) as sess:
        builder.add_meta_graph_and_variables(
            sess=sess,
            tags=[tf.saved_model.tag_constants.SERVING],
            signature_def_map={
                tf.saved_model.signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY: signature
            },
            legacy_init_op=legacy_op
        )
        builder.save()

def export_sfe_tf_graph(sfe, export_path):
    model = sfe.get_model()
    # since this is trained by keras we need to grab actual graph
    # built by tensorflow backend
    # reference: https://github.com/GoogleCloudPlatform/cloudml-samples/blob/master/census/keras/trainer/model.py
    save_sfe_to_serving(model._keras_model, export_path)

# @todo : TODO
def export_mrcnn_tf_graph(mrcnn, export_path):
    save_mrcnn_to_serving(mrcnn.keras_model, export_path)

def Program(raw_args):
    sfe = SemanticFeatureExtractor()
    export_sfe_tf_graph(sfe, os.path.join(sfe_config.MODEL_PATH, "coco/sfe"))
    export_mrcnn_tf_graph(sfe.get_base_model(), os.path.join(sfe_config.MODEL_PATH, "coco/mrcnn"))

if __name__ == "__main__":
    sys.exit(Program(sys.argv[1:]))