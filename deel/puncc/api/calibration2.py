# -*- coding: utf-8 -*-
# Copyright IRT Antoine de Saint Exupéry et Université Paul Sabatier Toulouse III - All
# rights reserved. DEEL is a research program operated by IVADO, IRT Saint Exupéry,
# CRIAQ and ANITI - https://www.deel.ai/
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
This module implements the core Calibrator and provides a collection of non-conformity scores and computations of the prediction sets.
"""
from abc import ABC
from abc import abstractmethod
from typing import Iterable
from typing import Optional
from typing import Union

import numpy as np
import pandas as pd

from deel.puncc.api.utils import check_alpha_calib
from deel.puncc.api.utils import EPSILON
from deel.puncc.api.utils import quantile
from deel.puncc.api.utils import supported_types_check


class NonConformityScores:
    class Classification:
        @staticmethod
        def RAPS_SCORE(lambd=0, k_reg=1):
            def _RAPS_SCORE(Y_pred, y_true):
                """APS nonconformity score.
                Given :math:`n` the number of classes,
                    :math:`Y_\text{{pred}} = (P_{\text{C}_1}, ..., P_{\text{C}_n})`

                Refer to https://arxiv.org/abs/2009.14193 for details.

                :param ndarray|DataFrame|Tensor Y_pred: :math:`Y_\text{{pred}} = (P_{\text{C}_1}, ..., P_{\text{C}_n})`
                    where :math:`P_{\text{C}_i}` is logit associated to class i.
                :param ndarray|DataFrame|Tensor y_true:

                :returns: APS nonconformity scores.
                :rtype: ndarray|DataFrame|Tensor
                """

                supported_types_check(Y_pred, y_true)
                if not isinstance(Y_pred, np.ndarray):
                    raise NotImplementedError(
                        "RAPS nonconformity scores only implemented for ndarrays"
                    )
                # Generate rand randomly from a uniform distribution
                rand = np.random.uniform(size=len(y_true))
                # Sort classes by descending probability order
                class_ranking = np.argsort(-Y_pred, axis=1)
                sorted_proba = -np.sort(-Y_pred, axis=1)
                # Cumulative probability mass (given the previous class ranking)
                sorted_cum_mass = sorted_proba.cumsum(axis=1)
                # Locate position of true label in the classes
                # sequence ranked by decreasing probability
                L = [
                    np.where(class_ranking[i] == y_true[i])[0][0]
                    for i in range(y_true.shape[0])
                ]
                # Threshold of cumulative probability mass to include the real class
                E = [sorted_cum_mass[i, L[i]] for i in range(y_true.shape[0])]
                E = [
                    E[i]
                    + (rand[i] - 1) * sorted_proba[i, L[i]]
                    + lambd * np.maximum((L[i] - k_reg + 1), 0)
                    for i in range(y_true.shape[0])
                ]
                return np.array(E)

            return _RAPS_SCORE

    class Regression:
        """Order y_pred, y_true is important here !"""

        @staticmethod
        def MAD(y_pred, y_true):
            """Mean Absolute Deviation (MAD).

            .. math::
                R = |y_{\text{true}}-y_\text{{pred}}|

            :param ndarray|DataFrame|Tensor y_pred:
            :param ndarray|DataFrame|Tensor y_true:

            :returns: mean absolute deviation.
            :rtype: ndarray|DataFrame|Tensor
            """
            supported_types_check(y_pred, y_true)
            diff = y_pred - y_true
            if isinstance(y_pred, np.ndarray):
                return np.absolute(diff)
            elif isinstance(y_pred, pd.DataFrame):
                return diff.abs()
            elif isinstance(y_pred, tf.Tensor):
                return tf.math.abs(diff)
            elif isinstance(y_pred, torch.Tensor):
                return torch.abs(diff)
            else:  # Sanity check, this should never happen.
                raise RuntimeError("Fatal Error. Type check failed !")

        @staticmethod
        def SCALED_MAD(Y_pred, y_true):
            """Scaled Mean Absolute Deviation (MAD).

            .. math::
                R = \frac{|Y_{\text{true}}-Y_\text{{pred}}|}{\sigma_\text{{pred}}}

            :param ndarray|DataFrame|Tensor Y_pred: :math:`Y_\text{{pred}}=(y_\text{{pred}}, \sigma_\text{{pred}})`
            :param ndarray|DataFrame|Tensor y_true: point observation.

            :returns: scaled mean absolute deviation.
            :rtype: ndarray|DataFrame|Tensor
            """
            supported_types_check(Y_pred, y_true)
            if Y_pred.shape[1] != 2:  # check Y_pred contains two predictions
                raise RuntimeError(
                    f"Each Y_pred must contain a point prediction and a dispersion estimation."
                )
            # check y_true is a collection of point observations
            if len(y_true.shape) != 1:
                raise RuntimeError(f"Each y_pred must contain a point observation.")

            if isinstance(Y_pred, pd.DataFrame):
                y_pred, var_pred = Y_pred.iloc[:, 0], Y_pred.iloc[:, 1]
            else:
                y_pred, var_pred = Y_pred[:, 0], Y_pred[:, 1]
            # MAD then Scaled MAD and computed
            mad = NonConformityScores.Regression.MAD(y_pred, y_true)
            return mad / (var_pred + EPSILON)

        @staticmethod
        def CQR_SCORE(Y_pred, y_true):
            """CQR nonconformity score.
            Considering :math:`Y_\text{{pred}} = (q_{\text{lo}}, q_{\text{hi}})`
            .. math::
                R = max\{q_{\text{lo}} - y_{\text{true}}, y_{\text{true}} - q_{\text{hi}}\}

            :param ndarray|DataFrame|Tensor Y_pred: :math:`Y_\text{{pred}} = (q_{\text{lo}}, q_{\text{hi}})`
                where :math:`q_{\text{lo}}` (resp. :math:`q_{\text{hi}}` is the lower (resp. higher) quantile prediction.
            :param ndarray|DataFrame|Tensor y_true:

            :returns: CQR nonconformity scores.
            :rtype: ndarray|DataFrame|Tensor
            """
            supported_types_check(Y_pred, y_true)
            if Y_pred.shape[1] != 2:  # check Y_pred contains two predictions
                raise RuntimeError(
                    f"Each Y_pred must contain lower and higher quantiles estimations."
                )

            # check y_true is a collection of point observations
            if len(y_true.shape) != 1:
                raise RuntimeError(f"Each y_pred must contain a point observation.")

            if isinstance(Y_pred, pd.DataFrame):
                q_lo, q_hi = Y_pred.iloc[:, 0], Y_pred.iloc[:, 1]
            else:
                q_lo, q_hi = Y_pred[:, 0], Y_pred[:, 1]

            diff_lo = q_lo - y_true
            diff_hi = y_true - q_hi

            if isinstance(diff_lo, np.ndarray):
                return np.maximum(diff_lo, diff_hi)
            elif isinstance(diff_lo, pd.DataFrame):
                raise NotImplementedError(
                    "CQR score not implemented for DataFrames. Please provide ndarray or tensors."
                )
            elif isinstance(diff_lo, tf.Tensor):
                return tf.math.maximum(diff_lo, diff_hi)
            elif isinstance(diff_lo, torch.Tensor):
                return torch.maximum(diff_lo, diff_hi)
            else:  # Sanity check, this should never happen.
                raise RuntimeError("Fatal Error. Type check failed !")


class PredictionSets:
    class Classification:
        @staticmethod
        def RAPS_SET(lambd=0, k_reg=1):
            def _RAPS_SET(Y_pred, scores_quantiles):
                pred_len = len(Y_pred)
                # Generate u randomly from a uniform distribution
                u = np.random.uniform(size=pred_len)
                # 1-alpha th empirical quantile of conformity scores
                tau = scores_quantiles
                # Rank classes by their probability
                idx_class_pred_ranking = np.argsort(-Y_pred, axis=1)
                sorted_proba = -np.sort(-Y_pred, axis=1)
                sorted_cum_mass = sorted_proba.cumsum(axis=1)
                # First sorted class for which the cumulative probability mass
                # exceeds the threshold "tau"
                penal_proba = [
                    sorted_proba[i]
                    + lambd
                    * np.maximum(
                        np.arange(1, len(sorted_cum_mass[i]) + 1) - k_reg,
                        0,  # Because classes are ranked by probability, o_x(y) corresponds [1, 2, 3, ...]
                    )
                    for i in range(pred_len)
                ]
                penal_cum_proba = [
                    sorted_cum_mass[i]
                    + lambd
                    * np.maximum(
                        np.arange(1, len(sorted_cum_mass[i]) + 1) - k_reg,
                        0,  # Because classes are ranked by probability, o_x(y) corresponds [1, 2, 3, ...]
                    )
                    for i in range(pred_len)
                ]
                L = [
                    len(np.where(penal_cum_proba[i] <= tau)[-1]) + 1
                    for i in range(pred_len)
                ]
                proba_excess = [
                    -sorted_cum_mass[i, L[i] - 1]
                    - lambd * np.maximum(L[i] - k_reg, 0)
                    + sorted_proba[i, L[i] - 1]
                    for i in range(pred_len)
                ]
                v = [
                    (tau - proba_excess[i]) / sorted_proba[i, L[i] - 1]
                    if (L[i] - 1) >= 0
                    else np.inf
                    for i in range(pred_len)
                ]
                # Build prediction set
                prediction_sets = list()
                for i in range(pred_len):
                    if v[i] <= u[i]:
                        cut_i = L[i] - 1
                    else:
                        cut_i = L[i]
                    if cut_i < 0:
                        prediction_sets.append([])
                    else:
                        prediction_sets.append(list(idx_class_pred_ranking[i, :cut_i]))
                return (prediction_sets,)

            return _RAPS_SET

    class Regression:
        @staticmethod
        def CONSTANT_INTERVAL(y_pred, scores_quantiles):
            supported_types_check(y_pred)
            y_lo = y_pred - scores_quantiles
            y_hi = y_pred + scores_quantiles
            return y_lo, y_hi

        @staticmethod
        def SCALED_INTERVAL(Y_pred, scores_quantiles):
            supported_types_check(Y_pred)
            if Y_pred.shape[1] != 2:  # check Y_pred contains two predictions
                raise RuntimeError(
                    f"Each Y_pred must contain a point prediction and a dispersion estimation."
                )
            if isinstance(Y_pred, pd.DataFrame):
                y_pred, var_pred = Y_pred.iloc[:, 0], Y_pred.iloc[:, 1]
            else:
                y_pred, var_pred = Y_pred[:, 0], Y_pred[:, 1]
            y_lo = y_pred - scores_quantiles * var_pred
            y_hi = y_pred + scores_quantiles * var_pred
            return y_lo, y_hi

        @staticmethod
        def CQR_INTERVAL(Y_pred, scores_quantiles):
            supported_types_check(Y_pred)
            if Y_pred.shape[1] != 2:  # check Y_pred contains two predictions
                raise RuntimeError(
                    f"Each Y_pred must contain lower and higher quantiles predictions, respectively."
                )
            if isinstance(Y_pred, pd.DataFrame):
                q_lo, q_hi = Y_pred.iloc[:, 0], Y_pred.iloc[:, 1]
            else:
                q_lo, q_hi = Y_pred[:, 0], Y_pred[:, 1]
            y_lo = q_lo - scores_quantiles
            y_hi = q_hi + scores_quantiles
            return y_lo, y_hi


class BaseCalibrator:
    """Calibrator class.

    :param callable nonconf_score_func: nonconformity score function
    :param callable pred_set_func:
    :param callable weight_func: function that takes as argument an array of
    features X and returns associated "conformality" weights, defaults to None.

    :raises NotImplementedError: provided :data:`weight_method` is not suitable.
    """

    @staticmethod
    def barber_weights(*, X, weights_calib):
        """Compute and normalize inference weights of the nonconformity distribution
        based on `Barber et al. <https://arxiv.org/abs/2202.13415>`.

        :param ndarray X: features array.
        :param ndarray weights_calib: weights assigned to the calibration samples.

        :returns: normalized weights.
        :rtype: ndarray
        """

        calib_size = len(weights_calib)
        # Computation of normalized weights
        sum_w_calib = np.sum(weights_calib)

        w_norm = np.zeros((len(X), calib_size + 1))
        for i in range(len(X)):
            w_norm[i, :calib_size] = weights_calib / (sum_w_calib + 1)
            w_norm[i, calib_size] = 1 / (sum_w_calib + 1)
        return w_norm

    def __init__(
        self,
        *,
        nonconf_score_func,
        pred_set_func,
        weight_func=None,
    ):
        self.nonconf_score_func = nonconf_score_func
        self.pred_set_func = pred_set_func
        self.weight_func = weight_func
        self._len_calib = 0
        self._residuals = None
        self._norm_weights = None

    def fit(
        self,
        *,
        y_true: Iterable,
        y_pred: Iterable,
    ) -> None:
        """Compute and store nonconformity scores on the calibration set.

        :param ndarray|DataFrame|Tensor y_true: true values.
        :param ndarray|DataFrame|Tensor y_pred: predicted values.
        :param Any kwargs: keyword arguments for the nonconformity score function.

        """
        # TODO check structure match in supported types
        self._residuals = self.nonconf_score_func(y_pred, y_true)
        self._len_calib = len(self._residuals)

    def calibrate(
        self,
        alpha: float,
        y_pred: Iterable,
        weights: Optional[Iterable] = None,
    ) -> tuple[Iterable, Optional[Iterable]]:
        """Compute calibrated prediction sets for new examples.

        :param float alpha: significance level (max miscoverage target).
        :param ndarray|DataFrame|Tensor y_pred: predicted values.
        :param Iterable weights: weights to be associated to the non-conformity
                                 scores. Defaults to None when all the scores
                                 are equiprobable.

        :returns: prediction set.
                  In case of regression, returns (y_lower, y_upper).
                  In case of classification, returns (classes,).
        :rtype: tuple[ndarray|DataFrame|Tensor, ndarray|DataFrame|Tensor]

        :raises RuntimeError: :meth:`calibrate` called before :meth:`fit`.
        :raise ValueError: failed check on :data:`alpha` w.r.t size of the calibration set.

        """
        if self._residuals is None:
            raise RuntimeError("Run `fit` method before calling `calibrate`.")

        # Check consistency of alpha w.r.t the size of calibration data
        check_alpha_calib(alpha=alpha, n=self._len_calib)

        residuals_Qs = list()

        # Fix to factorize the loop on weights:
        # Enables the loop even when the weights are not provided
        if weights is None:
            it_weights = [None]
        else:
            it_weights = weights

        for w in it_weights:
            infty_array = np.array([np.inf])
            lemma_residuals = np.concatenate((self._residuals, infty_array))
            residuals_Q = quantile(
                lemma_residuals,
                1 - alpha,
                w=w,
            )
            residuals_Qs.append(residuals_Q)
        return self.pred_set_func(y_pred, scores_quantiles=residuals_Qs)

    def set_norm_weights(self, norm_weights):
        """Setter of normalized weights associated to the nonconformity
        scores on the calibration set.

        :returns: normalized weights array.
        :rtype: ndarray
        """
        self._norm_weights = norm_weights

    def get_norm_weights(self):
        """Getter of normalized weights associated to the nonconformity
        scores on the calibration set.

        :param ndarray norm_weights: normalized weights array
        """
        return self._norm_weights


class CvPlusCalibrator:
    """Meta calibrator that combines the estimations nonconformity
    scores by each K-Fold calibrator and produces associated prediction
    intervals based on CV+ method.

    Attributes:
        kfold_calibrators_dict: dictionary of calibrators for each K-fold
                                (disjoint calibration subsets). Each calibrator
                                needs to priorly estimate the nonconformity
                                scores w.r.t the associated calibration fold.

    """

    def __init__(self, kfold_calibrators: dict):
        self.kfold_calibrators_dict = kfold_calibrators
        # Sanity checks:
        #   - The collection of calibrators is not None
        if kfold_calibrators is None:
            raise RuntimeError("Calibrators not defined.")
        #   - The calibrators in the collection are not None
        for k, calibrator in self.kfold_calibrators_dict.items():
            if calibrator is None:
                raise RuntimeError(f"Fold {k} calibrator is not defined.")

    def fit(self) -> None:
        """Check if all calibrators have already been fitted."""

        for k, calibrator in self.kfold_calibrators_dict.items():
            if calibrator._residuals is None:
                error_msg = (
                    f"Fold {k} calibrator should have priorly "
                    + "estimated its residuals."
                )
                raise RuntimeError(error_msg)

    def calibrate(
        self,
        *,
        X: Iterable,
        kfold_predictors_dict: dict,
        alpha: float,
    ) -> tuple[Iterable, Iterable]:
        concat_residuals_lo = None
        concat_residuals_hi = None
        """Compute calibrated prediction intervals for new examples X.

        :param ndarray|DataFrame|Tensor X: test features.
        :param dict kfold_predictors_dict: dictionnary of predictors trained for each fold on the fit subset.
        :param float alpha: maximum miscoverage target.

        :returns: y_lower, y_upper.
        :rtype: tuple[ndarray|DataFrame|Tensor, ndarray|DataFrame|Tensor]
        """

        # Init the collection of upper and lower bounds of the K-fold's PIs
        concat_y_lo = None
        concat_y_hi = None

        for k, predictor in kfold_predictors_dict.items():
            # Predictions
            y_pred = predictor.predict(X)

            if y_pred is None:
                raise RuntimeError("No point predictor provided with cv+.")

            y_pred = np.reshape(y_pred, (len(y_pred), 1))

            # Residuals
            residuals = self.kfold_calibrators_dict[k]._residuals
            residuals = np.reshape(residuals, (1, len(residuals)))

            if concat_y_lo is None or concat_y_hi is None:
                concat_y_lo, concat_y_hi = PredictionSets.Regression.CONSTANT_INTERVAL(y_pred, residuals)  # type: ignore
            else:
                y_lo, y_hi = PredictionSets.Regression.CONSTANT_INTERVAL(
                    y_pred, residuals
                )
                concat_y_lo = np.concatenate(
                    [concat_y_lo, y_lo], axis=1  # type: ignore
                )
                concat_y_hi = np.concatenate([concat_y_hi, y_hi], axis=1)
        # sanity check
        if concat_y_lo is None or concat_y_hi is None:
            raise RuntimeError("This should never happen.")
        else:
            y_lo = (-1) * np.quantile(
                (-1) * concat_y_lo, 1 - alpha, axis=1, method="inverted_cdf"
            )
            y_hi = np.quantile(concat_y_hi, 1 - alpha, axis=1, method="inverted_cdf")
            return y_lo, y_hi
