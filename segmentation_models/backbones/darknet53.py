import os

from keras_applications.imagenet_utils import _obtain_input_shape
from tensorflow.python.keras import Input, Model
from tensorflow.python.keras.applications import imagenet_utils
from tensorflow.python.keras.utils.data_utils import get_file
from tensorflow.python.keras.utils.layer_utils import get_source_inputs
from functools import wraps, reduce

import tensorflow.keras.backend as K
from tensorflow.keras.layers import Conv2D, DepthwiseConv2D, Concatenate, MaxPooling2D, BatchNormalization, \
    Activation, UpSampling2D, ZeroPadding2D, GlobalAveragePooling2D, Reshape, Flatten, Softmax, GlobalMaxPooling2D, Add
from tensorflow.keras.layers import LeakyReLU
from tensorflow.keras.regularizers import l2

BASE_WEIGHT_PATH = (
    'https://github.com/david8862/keras-YOLOv3-model-set/'
    'releases/download/v1.0.1/')

def compose(*funcs):
    """Compose arbitrarily many functions, evaluated left to right.

    Reference: https://mathieularose.com/function-composition-in-python/
    """
    # return lambda x: reduce(lambda v, f: f(v), funcs, x)
    if funcs:
        return reduce(lambda f, g: lambda *a, **kw: g(f(*a, **kw)), funcs)
    else:
        raise ValueError('Composition of empty sequence not supported.')


@wraps(Conv2D)
def DarknetConv2D(*args, **kwargs):
    """Wrapper to set Darknet parameters for Convolution2D."""
    darknet_conv_kwargs = {'kernel_regularizer': l2(5e-4)}
    darknet_conv_kwargs['padding'] = 'valid' if kwargs.get('strides')==(2,2) else 'same'
    darknet_conv_kwargs.update(kwargs)
    return Conv2D(*args, **darknet_conv_kwargs)


@wraps(DepthwiseConv2D)
def DarknetDepthwiseConv2D(*args, **kwargs):
    """Wrapper to set Darknet parameters for Convolution2D."""
    darknet_conv_kwargs = {'kernel_regularizer': l2(5e-4)}
    darknet_conv_kwargs['padding'] = 'valid' if kwargs.get('strides')==(2,2) else 'same'
    darknet_conv_kwargs.update(kwargs)
    return DepthwiseConv2D(*args, **darknet_conv_kwargs)

def Darknet_Depthwise_Separable_Conv2D_BN_Leaky(filters, kernel_size=(3, 3), block_id_str=None, **kwargs):
    """Depthwise Separable Convolution2D."""
    if not block_id_str:
        block_id_str = str(K.get_uid())
    no_bias_kwargs = {'use_bias': False}
    no_bias_kwargs.update(kwargs)
    return compose(
        DarknetDepthwiseConv2D(kernel_size, name='conv_dw_' + block_id_str, **no_bias_kwargs),
        BatchNormalization(name='conv_dw_%s_bn' % block_id_str),
        LeakyReLU(alpha=0.1, name='conv_dw_%s_leaky_relu' % block_id_str),
        Conv2D(filters, (1,1), padding='same', use_bias=False, strides=(1, 1), name='conv_pw_%s' % block_id_str),
        BatchNormalization(name='conv_pw_%s_bn' % block_id_str),
        LeakyReLU(alpha=0.1, name='conv_pw_%s_leaky_relu' % block_id_str))


def Depthwise_Separable_Conv2D_BN_Leaky(filters, kernel_size=(3, 3), block_id_str=None):
    """Depthwise Separable Convolution2D."""
    if not block_id_str:
        block_id_str = str(K.get_uid())
    return compose(
        DepthwiseConv2D(kernel_size, padding='same', name='conv_dw_' + block_id_str),
        BatchNormalization(name='conv_dw_%s_bn' % block_id_str),
        LeakyReLU(alpha=0.1, name='conv_dw_%s_leaky_relu' % block_id_str),
        Conv2D(filters, (1,1), padding='same', use_bias=False, strides=(1, 1), name='conv_pw_%s' % block_id_str),
        BatchNormalization(name='conv_pw_%s_bn' % block_id_str),
        LeakyReLU(alpha=0.1, name='conv_pw_%s_leaky_relu' % block_id_str))


def DarknetConv2D_BN_Leaky(*args, **kwargs):
    """
    Darknet Convolution2D followed by BatchNormalization and LeakyReLU.
    """
    no_bias_kwargs = {'use_bias': False}
    no_bias_kwargs.update(kwargs)
    return compose(
        DarknetConv2D(*args, **no_bias_kwargs),
        BatchNormalization(),
        LeakyReLU(alpha=0.1))


def mish(x):
    return x * K.tanh(K.softplus(x))

def DarknetConv2D_BN_Mish(*args, **kwargs):
    """Darknet Convolution2D followed by BatchNormalization and LeakyReLU."""
    no_bias_kwargs = {'use_bias': False}
    no_bias_kwargs.update(kwargs)
    return compose(
        DarknetConv2D(*args, **no_bias_kwargs),
        BatchNormalization(),
        Activation(mish))


def Spp_Conv2D_BN_Leaky(x, num_filters):
    y1 = MaxPooling2D(pool_size=(5,5), strides=(1,1), padding='same')(x)
    y2 = MaxPooling2D(pool_size=(9,9), strides=(1,1), padding='same')(x)
    y3 = MaxPooling2D(pool_size=(13,13), strides=(1,1), padding='same')(x)

    y = compose(
            Concatenate(),
            DarknetConv2D_BN_Leaky(num_filters, (1,1)))([y1, y2, y3, x])
    return y





def resblock_body(x, num_filters, num_blocks, all_narrow=True):
    '''A series of resblocks starting with a downsampling Convolution2D'''
    # Darknet uses left and top padding instead of 'same' mode
    x = ZeroPadding2D(((1, 0), (1, 0)))(x)
    x = DarknetConv2D_BN_Mish(num_filters, (3, 3), strides=(2, 2))(x)

    res_connection = DarknetConv2D_BN_Mish(num_filters // 2 if all_narrow else num_filters, (1, 1))(x)
    x = DarknetConv2D_BN_Mish(num_filters // 2 if all_narrow else num_filters, (1, 1))(x)

    for i in range(num_blocks):
        y = compose(
            DarknetConv2D_BN_Mish(num_filters // 2, (1, 1)),
            DarknetConv2D_BN_Mish(num_filters // 2 if all_narrow else num_filters, (3, 3)))(x)
        x = Add()([x, y])

    x = DarknetConv2D_BN_Mish(num_filters // 2 if all_narrow else num_filters, (1, 1))(x)
    x = Concatenate()([x, res_connection])

    return DarknetConv2D_BN_Mish(num_filters, (1, 1))(x)


def csp_darknet53_body(x):
    '''CSPDarknet53 body having 52 Convolution2D layers'''
    x = DarknetConv2D_BN_Mish(32, (3, 3))(x)
    x = resblock_body(x, 64, 1, False)
    x = resblock_body(x, 128, 2)
    x = resblock_body(x, 256, 8)
    x = resblock_body(x, 512, 8)
    x = resblock_body(x, 1024, 4)
    return x


def csp_darknet53(input_shape=None,
                  input_tensor=None,
                  include_top=True,
                  weights='imagenet',
                  pooling=None,
                  classes=1000,
                  **kwargs):
    """Generate cspdarknet53 model for Imagenet classification."""

    if not (weights in {'imagenet', None} or os.path.exists(weights)):
        raise ValueError('The `weights` argument should be either '
                         '`None` (random initialization), `imagenet` '
                         '(pre-training on ImageNet), '
                         'or the path to the weights file to be loaded.')

    if weights == 'imagenet' and include_top and classes != 1000:
        raise ValueError('If using `weights` as `"imagenet"` with `include_top`'
                         ' as true, `classes` should be 1000')

    # Determine proper input shape
    input_shape = _obtain_input_shape(input_shape,
                                      default_size=224,
                                      min_size=28,
                                      data_format=K.image_data_format(),
                                      require_flatten=include_top,
                                      weights=weights)

    if input_tensor is None:
        img_input = Input(shape=input_shape)
    else:
        img_input = input_tensor

    x = csp_darknet53_body(img_input)

    if include_top:
        model_name = 'cspdarknet53'
        x = GlobalAveragePooling2D(name='avg_pool')(x)
        x = Reshape((1, 1, 1024))(x)
        x = DarknetConv2D(classes, (1, 1))(x)
        x = Flatten()(x)
        x = Softmax(name='Predictions/Softmax')(x)
    else:
        model_name = 'cspdarknet53_headless'
        if pooling == 'avg':
            x = GlobalAveragePooling2D(name='avg_pool')(x)
        elif pooling == 'max':
            x = GlobalMaxPooling2D(name='max_pool')(x)

    # Ensure that the model takes into account
    # any potential predecessors of `input_tensor`.
    if input_tensor is not None:
        inputs = get_source_inputs(input_tensor)
    else:
        inputs = img_input

    # Create model.
    model = Model(inputs, x, name=model_name)

    # Load weights.
    if weights == 'imagenet':
        if include_top:
            file_name = 'cspdarknet53_weights_tf_dim_ordering_tf_kernels_224.h5'
            weight_path = BASE_WEIGHT_PATH + file_name
        else:
            file_name = 'cspdarknet53_weights_tf_dim_ordering_tf_kernels_224_no_top.h5'
            weight_path = BASE_WEIGHT_PATH + file_name

        weights_path = get_file(file_name, weight_path, cache_subdir='models')
        model.load_weights(weights_path)
    elif weights is not None:
        model.load_weights(weights)

    return model


def preprocess_input(x, **kwargs):
    """Preprocesses a numpy array encoding a batch of images.
    # Arguments
        x: a 4D numpy array consists of RGB values within [0, 255].
    # Returns
        Preprocessed array.
    """
    return imagenet_utils.preprocess_input(x, mode='tf', **kwargs)