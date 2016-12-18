"""
Baseline for machine learning project on road segmentation.
This simple baseline consits of a CNN with two convolutional+pooling layers with a soft-max loss

Credits: Aurelien Lucchi, ETH Zürich
"""



import gzip
import os
import sys
import urllib
import scipy.misc
import matplotlib.image as mpimg
from PIL import Image
from scipy import ndimage as ndi
import math
import code
import tensorflow.python.platform
import numpy
import random
import tensorflow as tf

NUM_CHANNELS = 3  # RGB images
PIXEL_DEPTH = 255
NUM_LABELS = 2
TRAINING_SIZE = 5  # ideally: 100
TEST_SIZE = 5  # ideally: 50
VALIDATION_SIZE = 30  # Size of the validation set.
SEED = None  # Set to None for random seed.
BATCH_SIZE = 16  # 64 (?)
NUM_EPOCHS = 1
RESTORE_MODEL = False  # If True, restore existing model instead of training a new one
RECORDING_STEP = 1000
SAVING_MODEL_TO_DISK_STEP = 10000
BATCH_SIZE_FOR_PREDICTION = 10000

# Set image patch size in pixels (should be a multiple of 4 for some reason)
IMG_PATCH_SIZE = 48  # ideally, like 48

tf.app.flags.DEFINE_string('train_dir', 'tmp/mnist',
                           """Directory where to write event logs """
                           """and checkpoint.""")
FLAGS = tf.app.flags.FLAGS

# paths to stuff
data_dir = 'training/'
train_data_filename = data_dir + 'images/'
train_labels_filename = data_dir + 'groundtruth/'
test_data_filename = 'test_set_images/test_'



def pad_image(im):
    imgwidth = im.shape[0]
    imgheight = im.shape[1]
    is_2d = len(im.shape) < 3
    assert(is_2d is False)

    # pad the image with 0.5 (gray)
    if is_2d:
        padded_image = numpy.full(
            (IMG_PATCH_SIZE + im.shape[0] + IMG_PATCH_SIZE, IMG_PATCH_SIZE + im.shape[1] + IMG_PATCH_SIZE), 0.5,
            dtype='float32')
        padded_image[IMG_PATCH_SIZE:IMG_PATCH_SIZE + im.shape[0], IMG_PATCH_SIZE:IMG_PATCH_SIZE + im.shape[1]] = im
    else:
        padded_image = numpy.full(
            (IMG_PATCH_SIZE + im.shape[0] + IMG_PATCH_SIZE, IMG_PATCH_SIZE + im.shape[1] + IMG_PATCH_SIZE, im.shape[2]),
            0.5, dtype='float32')
        padded_image[IMG_PATCH_SIZE:IMG_PATCH_SIZE + im.shape[0], IMG_PATCH_SIZE:IMG_PATCH_SIZE + im.shape[1], :] = im
    return padded_image


def get_padded_images(filename, num_images):
    imgs = []
    for i in range(1, num_images+1):
        imageid = "satImage_%.3d" % i
        image_filename = filename + imageid + ".png"
        if os.path.isfile(image_filename):
            print ('Loading ' + image_filename)
            img = mpimg.imread(image_filename)
            imgs.append(pad_image(img))
        else:
            print ('File ' + image_filename + ' does not exist')
    return imgs


def extract_samples_of_labels(filename, num_images):
    gt_imgs = []
    for i in range(1, num_images+1):
        imageid = "satImage_%.3d" % i
        image_filename = filename + imageid + ".png"
        if os.path.isfile(image_filename):
            print ('Loading ' + image_filename)
            img = mpimg.imread(image_filename)
            gt_imgs.append(img)
        else:
            print ('File ' + image_filename + ' does not exist')

    num_images = len(gt_imgs)
    ret = [[],[]]
    for k in range(num_images):
        for i in range(0, gt_imgs[k].shape[1]): # height
            for j in range(0, gt_imgs[k].shape[0]): # width
                is_on = gt_imgs[k][j,i] > 0.5
                ret[is_on].append((k,j,i))
    return ret


def get_patch(padded_image, j, i):
    j += IMG_PATCH_SIZE
    i += IMG_PATCH_SIZE
    assert(len(padded_image.shape) == 3)
    ret = padded_image[j-IMG_PATCH_SIZE//2:j+IMG_PATCH_SIZE//2, i-IMG_PATCH_SIZE//2:i+IMG_PATCH_SIZE//2, :]
    assert(ret.shape == (IMG_PATCH_SIZE, IMG_PATCH_SIZE, 3))
    return ret


def get_data_from_tuples(train_tuples, train_images_padded):
    ret = []
    for (k,j,i) in train_tuples:
        assert(len(train_images_padded) > k)
        patch = get_patch(train_images_padded[k], j, i)
        assert(len(patch.shape) == 3)
        ret.append(patch)
    return numpy.array(ret)


def get_labels_from_simple_labels(train_labels_simple):
    ret = []
    for x in train_labels_simple:
        if x == 0:
            ret.append([1, 0])
        else:
            ret.append([0, 1])
    return numpy.array(ret)


def error_rate(predictions, labels):
    """Return the error rate based on dense predictions and 1-hot labels."""
    return 100.0 - (
        100.0 *
        numpy.sum(numpy.argmax(predictions, 1) == numpy.argmax(labels, 1)) /
        predictions.shape[0])


# Convert array of labels to an image
def label_to_img(imgwidth, imgheight, labels):
    array_labels = numpy.zeros([imgwidth, imgheight])
    idx = 0
    for i in range(0,imgheight):
        for j in range(0,imgwidth):
            if labels[idx][0] > 0.5:
                l = 1
            else:
                l = 0
            array_labels[j, i] = l
            idx = idx + 1
    return array_labels


def img_float_to_uint8(img):
    rimg = img - numpy.min(img)
    rimg = (rimg / numpy.max(rimg) * PIXEL_DEPTH).round().astype(numpy.uint8)
    return rimg


def concatenate_images(img, gt_img):
    nChannels = len(gt_img.shape)
    w = gt_img.shape[0]
    h = gt_img.shape[1]
    if nChannels == 3:
        cimg = numpy.concatenate((img, gt_img), axis=1)
    else:
        gt_img_3c = numpy.zeros((w, h, 3), dtype=numpy.uint8)
        gt_img8 = img_float_to_uint8(gt_img)
        gt_img_3c[:,:,0] = gt_img8
        gt_img_3c[:,:,1] = gt_img8
        gt_img_3c[:,:,2] = gt_img8
        img8 = img_float_to_uint8(img)
        cimg = numpy.concatenate((img8, gt_img_3c), axis=1)
    return cimg


def make_img_overlay(img, predicted_img):
    w = img.shape[0]
    h = img.shape[1]
    color_mask = numpy.zeros((w, h, 3), dtype=numpy.uint8)
    color_mask[:,:,0] = predicted_img*PIXEL_DEPTH

    img8 = img_float_to_uint8(img)
    background = Image.fromarray(img8, 'RGB').convert("RGBA")
    overlay = Image.fromarray(color_mask, 'RGB').convert("RGBA")
    new_img = Image.blend(background, overlay, 0.2)
    return new_img


def main(argv=None):  # pylint: disable=unused-argument


    # preparing tuples takes ~20 seconds, but longer if rewritten to numpy
    train_images_padded = get_padded_images(train_data_filename, TRAINING_SIZE)
    train_tuples_of_label = extract_samples_of_labels(train_labels_filename, TRAINING_SIZE)

    print('Tuples and labels are loaded')

    c0 = len(train_tuples_of_label[0])
    c1 = len(train_tuples_of_label[1])
    print ('Number of data points per class: c0 =', c0, ', c1 =', c1)

    print ('Balancing training tuples...')
    assert(c0 > c1)
    # add copies of c1 so that c1 > c0, then truncate c1 to become c0
    random.shuffle(train_tuples_of_label[1])
    multiplier = int(math.ceil(c0 / c1))
    train_tuples_of_label[1] *= multiplier  # e.g. [1,2,3] * 2 = [1,2,3,1,2,3]
    del train_tuples_of_label[1][c0:]  # truncate
    c1 = len(train_tuples_of_label[1])
    assert(c0 == c1)

    # now merge the training tuples: first c0, then c1
    train_tuples = numpy.array(train_tuples_of_label[0] + train_tuples_of_label[1])
    train_labels_simple = numpy.array([0] * c0 + [1] * c1)

    train_size = len(train_tuples)

    print('Training tuples are ready')




    # This is where training samples and labels are fed to the graph.
    # These placeholder nodes will be fed a batch of training data at each
    # training step using the {feed_dict} argument to the Run() call below.
    train_data_node = tf.placeholder(
        tf.float32,
        shape=(BATCH_SIZE, IMG_PATCH_SIZE, IMG_PATCH_SIZE, NUM_CHANNELS))
    train_labels_node = tf.placeholder(tf.float32,
                                       shape=(BATCH_SIZE, NUM_LABELS))

    # The variables below hold all the trainable weights. They are passed an
    # initial value which will be assigned when when we call:
    # {tf.initialize_all_variables().run()}
    conv1_weights = tf.Variable(
        tf.truncated_normal([5, 5, NUM_CHANNELS, 32],  # 5x5 filter, depth 32.
                            stddev=0.1,
                            seed=SEED))
    conv1_biases = tf.Variable(tf.zeros([32]))
    conv2_weights = tf.Variable(
        tf.truncated_normal([5, 5, 32, 64],
                            stddev=0.1,
                            seed=SEED))
    conv2_biases = tf.Variable(tf.constant(0.1, shape=[64]))
    fc1_weights = tf.Variable(  # fully connected, depth 512.
        tf.truncated_normal([int(IMG_PATCH_SIZE / 4 * IMG_PATCH_SIZE / 4 * 64), 512],
                            stddev=0.1,
                            seed=SEED))
    fc1_biases = tf.Variable(tf.constant(0.1, shape=[512]))
    fc2_weights = tf.Variable(
        tf.truncated_normal([512, NUM_LABELS],
                            stddev=0.1,
                            seed=SEED))
    fc2_biases = tf.Variable(tf.constant(0.1, shape=[NUM_LABELS]))


    # Get prediction for given input image 
    def get_prediction(img):
        # TODO - cache the result

        # TODO - this gets progressively slower as we iterate. use placeholder instead of constant for invoking TF?

        padded_image = pad_image(img)

        pairs_JI = []
        for i in range(img.shape[1]):  # height
            for j in range(img.shape[0]):  # width
                pairs_JI.append((j,i))
        output_predictions = []  # array of output predictions
        for offset in range(0, len(pairs_JI), BATCH_SIZE_FOR_PREDICTION):
            print('Beginning offset', offset, 'out of', len(pairs_JI))
            current_pairs_JI = pairs_JI[offset : offset+BATCH_SIZE_FOR_PREDICTION]
            current_data = numpy.asarray([get_patch(padded_image,j,i) for (j,i) in current_pairs_JI])
            data_node = tf.constant(current_data)
            output = tf.nn.softmax(model(data_node))
            output_predictions.append(s.run(output))
        output_prediction = numpy.concatenate(output_predictions)
        img_prediction = label_to_img(img.shape[0], img.shape[1], output_prediction)

        # the hole-filling procedure
        img_prediction = ndi.binary_fill_holes(img_prediction, structure=numpy.ones((3, 3))).astype(int)

        return img_prediction

    # Get a concatenation of the prediction and groundtruth for given input file
    def get_prediction_with_groundtruth(filename, image_idx):

        imageid = "satImage_%.3d" % image_idx
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        img_prediction = get_prediction(img)
        cimg = concatenate_images(img, img_prediction)

        return cimg
    

    # Get prediction overlaid on the original image for given input file
    def get_prediction_with_overlay(filename, image_idx):

        imageid = "satImage_%.3d" % image_idx
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        img_prediction = get_prediction(img)
        oimg = make_img_overlay(img, img_prediction)

        return oimg


    def get_prediction_with_overlay_test(filename, image_idx):

        imageid = "test_" + str(image_idx)
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        img_prediction = get_prediction(img)
        oimg = make_img_overlay(img, img_prediction)

        return oimg


    # We will replicate the model structure for the training subgraph, as well
    # as the evaluation subgraphs, while sharing the trainable parameters.
    def model(data, train=False):
        """The Model definition."""
        # 2D convolution, with 'SAME' padding (i.e. the output feature map has
        # the same size as the input). Note that {strides} is a 4D array whose
        # shape matches the data layout: [image index, y, x, depth].
        conv = tf.nn.conv2d(data,
                            conv1_weights,
                            strides=[1, 1, 1, 1],
                            padding='SAME')
        # Bias and rectified linear non-linearity.
        relu = tf.nn.relu(tf.nn.bias_add(conv, conv1_biases))
        # Max pooling. The kernel size spec {ksize} also follows the layout of
        # the data. Here we have a pooling window of 2, and a stride of 2.
        pool = tf.nn.max_pool(relu,
                              ksize=[1, 2, 2, 1],
                              strides=[1, 2, 2, 1],
                              padding='SAME')

        conv2 = tf.nn.conv2d(pool,
                            conv2_weights,
                            strides=[1, 1, 1, 1],
                            padding='SAME')
        relu2 = tf.nn.relu(tf.nn.bias_add(conv2, conv2_biases))
        pool2 = tf.nn.max_pool(relu2,
                              ksize=[1, 2, 2, 1],
                              strides=[1, 2, 2, 1],
                              padding='SAME')

        # Uncomment these lines to check the size of each layer
        # print 'data ' + str(data.get_shape())
        # print 'conv ' + str(conv.get_shape())
        # print 'relu ' + str(relu.get_shape())
        # print 'pool ' + str(pool.get_shape())
        # print 'pool2 ' + str(pool2.get_shape())


        # Reshape the feature map cuboid into a 2D matrix to feed it to the
        # fully connected layers.
        pool_shape = pool2.get_shape().as_list()
        reshape = tf.reshape(
            pool2,
            [pool_shape[0], pool_shape[1] * pool_shape[2] * pool_shape[3]])
        # Fully connected layer. Note that the '+' operation automatically
        # broadcasts the biases.
        hidden = tf.nn.relu(tf.matmul(reshape, fc1_weights) + fc1_biases)
        # Add a 50% dropout during training only. Dropout also scales
        # activations such that no rescaling is needed at evaluation time.
        #if train:
        #    hidden = tf.nn.dropout(hidden, 0.5, seed=SEED)
        out = tf.matmul(hidden, fc2_weights) + fc2_biases

        return out

    # Training computation: logits + cross-entropy loss.
    logits = model(train_data_node, True) # BATCH_SIZE*NUM_LABELS
    # print 'logits = ' + str(logits.get_shape()) + ' train_labels_node = ' + str(train_labels_node.get_shape())
    loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
        logits, train_labels_node))

    all_params_node = [conv1_weights, conv1_biases, conv2_weights, conv2_biases, fc1_weights, fc1_biases, fc2_weights, fc2_biases]
    all_grads_node = tf.gradients(loss, all_params_node)
    all_grad_norms_node = []
    for i in range(0, len(all_grads_node)):
        norm_grad_i = tf.global_norm([all_grads_node[i]])
        all_grad_norms_node.append(norm_grad_i)

    # L2 regularization for the fully connected parameters.
    regularizers = (tf.nn.l2_loss(fc1_weights) + tf.nn.l2_loss(fc1_biases) +
                    tf.nn.l2_loss(fc2_weights) + tf.nn.l2_loss(fc2_biases))
    # Add the regularization term to the loss.
    loss += 5e-4 * regularizers

    # Optimizer: set up a variable that's incremented once per batch and
    # controls the learning rate decay.
    batch = tf.Variable(0)
    # Decay once per epoch, using an exponential schedule starting at 0.01.
    learning_rate = tf.train.exponential_decay(
        0.01,                # Base learning rate.
        batch * BATCH_SIZE,  # Current index into the dataset.
        train_size,          # Decay step.
        0.80,                # Decay rate. (much increased since train_size is huge)
        staircase=True)

    # Use simple momentum for the optimization.
    optimizer = tf.train.MomentumOptimizer(learning_rate, 0.0).minimize(loss, global_step=batch)

    # Predictions for the minibatch, validation set and test set.
    train_prediction = tf.nn.softmax(logits)
    # We'll compute them only once in a while by calling their {eval()} method.

    # Add ops to save and restore all the variables.
    saver = tf.train.Saver()

    # Create a local session to run this computation.
    with tf.Session() as s:


        # TODO: resuming the training from partial results
        if RESTORE_MODEL:
            # Restore variables from disk.
            saver.restore(s, FLAGS.train_dir + "/model.ckpt")
            print("Model restored.")

        else:
            # Run all the initializers to prepare the trainable parameters.
            tf.initialize_all_variables().run()

            print ('Initialized!')
            # Loop through training steps.
            print ('Total number of iterations = ' + str(int(NUM_EPOCHS * train_size / BATCH_SIZE)))

            training_indices = range(train_size)

            for iepoch in range(NUM_EPOCHS):
                print("Starting epoch number", iepoch+1)

                # Permute training indices
                perm_indices = numpy.random.permutation(training_indices)

                for step in range (int(train_size / BATCH_SIZE)):

                    offset = (step * BATCH_SIZE) % (train_size - BATCH_SIZE)
                    batch_indices = perm_indices[offset:(offset + BATCH_SIZE)]

                    # Compute the offset of the current minibatch in the data.
                    # Note that we could use better randomization across epochs.

                    batch_data = get_data_from_tuples(train_tuples[batch_indices, :], train_images_padded)
                    batch_labels = get_labels_from_simple_labels(train_labels_simple[batch_indices])

                    # This dictionary maps the batch data (as a numpy array) to the
                    # node in the graph is should be fed to.
                    feed_dict = {train_data_node: batch_data,
                                 train_labels_node: batch_labels}

                    # Run the graph and fetch some of the nodes.
                    _, l, lr, predictions = s.run(
                        [optimizer, loss, learning_rate, train_prediction],
                        feed_dict=feed_dict)

                    if step % RECORDING_STEP == 0:
                        print('Epoch %.2f' % (float(step) * BATCH_SIZE / train_size))
                        print('Minibatch loss: %.3f, learning rate: %.6f' % (l, lr))
                        print('Minibatch error: %.1f%%' % error_rate(predictions, batch_labels))

                        sys.stdout.flush()

                    if step % SAVING_MODEL_TO_DISK_STEP == 0:
                        # Save the variables to disk.
                        save_path = saver.save(s, FLAGS.train_dir + "/model.ckpt")
                        print("Model saved in file: %s" % save_path)

        # Getting the prediction and overlay for the training images. Stored in 'predictions_training'
        print ("Running prediction on training set")
        prediction_training_dir = "predictions_training/"
        for i in range(1, TRAINING_SIZE+1):
            print("Processing image", i)
            imageid = "satImage_%.3d" % i
            image_filename = train_data_filename + imageid + ".png"
            pimg = get_prediction(mpimg.imread(image_filename))
            pimg = 1 - pimg
            scipy.misc.imsave(prediction_training_dir + "prediction_" + str(i) + ".png", pimg)
        
        # Getting the prediction and overlay for the test images. Stored in 'predictions_test'
        print ("Running prediction on test set")
        prediction_test_dir = "predictions_test/"
        if not os.path.isdir(prediction_test_dir):
            os.mkdir(prediction_test_dir)
        for i in range(1, TEST_SIZE+1):
            print("Processing image", i)
            filename_test = test_data_filename + str(i) + '/test_' + str(i) + '.png'
            pimg = get_prediction(mpimg.imread(filename_test))
            pimg = 1 - pimg
            scipy.misc.imsave(prediction_test_dir + "prediction_" + str(i) + ".png", pimg)
            oimg = get_prediction_with_overlay_test(test_data_filename + str(i) + '/', i)
            oimg.save(prediction_test_dir + "overlay_" + str(i) + ".png")

if __name__ == '__main__':
    tf.app.run()
