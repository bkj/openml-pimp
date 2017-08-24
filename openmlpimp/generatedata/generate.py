
import argparse
import openml
import openmlpimp
import random
import traceback
import sklearn

from openml.exceptions import OpenMLServerException
from collections import OrderedDict

import autosklearn.constants
from autosklearn.util.pipeline import get_configuration_space


def parse_args():
    parser = argparse.ArgumentParser(description='Generate data for openml-pimp project')
    all_classifiers = ['adaboost', 'bernoulli_nb', 'decision_tree', 'extra_trees', 'gaussian_nb', 'gradient_boosting',
                       'k_nearest_neighbors', 'lda', 'liblinear_svc', 'libsvm_svc', 'multinomial_nb', 'passive_aggressive',
                       'qda', 'random_forest', 'sgd']
    all_classifiers = ['adaboost', 'decision_tree', 'libsvm_svc', 'random_forest', 'sgd']
    parser.add_argument('--n_executions', type=int,  default=100, help='number of runs to be executed. ')
    parser.add_argument('--study_id', type=int, default=None, help='the tag to obtain the tasks from')
    parser.add_argument('--openml_server', type=str, default=None, help='the openml server location')
    parser.add_argument('--openml_taskid', type=int, nargs="+", default=None, help='the openml task id to execute')
    parser.add_argument('--openml_apikey', type=str, required=True, default=None, help='the apikey to authenticate to OpenML')
    parser.add_argument('--classifier', type=str, choices=all_classifiers, default='decision_tree', help='the classifier to execute')

    args = parser.parse_args()
    if args.openml_taskid is not None and args.study_id is not None:
        raise ValueError('can only set openml_taskid XOR openml_tag')
    if args.openml_taskid is None and args.study_id is None:
        raise ValueError('set either openml_taskid or openml_tag')
    return args


def get_probability_fn(configuration_space, all_task_ids):
    classifier = openmlpimp.utils.obtain_classifier(configuration_space, None)
    flow = openml.flows.sklearn_to_flow(classifier)
    flow_id = openml.flows.flow_exists(flow.name, flow.external_version)

    # obtain task counts
    task_counts = {}
    if flow_id: task_counts = openmlpimp.utils.task_counts(flow_id)

    # add tasks with count 0
    for task_id in all_task_ids:
        if task_id not in task_counts:
            task_counts[task_id] = 0

    max_value = 0
    if len(task_counts) > 0: max_value = max(1, max(task_counts.values()))

    # invert
    probability_fn = {}
    for task_id in task_counts:
        probability_fn[task_id] = max_value - task_counts[task_id]

     # sort (because why not)
    return OrderedDict(sorted(probability_fn.items()))


def check_classifier_equals(run_id, classifier):
    params_orig = set(classifier.get_params().keys())
    run_prime = openml.runs.get_run(run_id)
    classif_prime = openml.setups.initialize_model(run_prime.setup_id)
    params_prime = set(classif_prime.get_params().keys())
    if params_prime != params_orig:
        raise ValueError('params set not equal!')

    for param, value_prime in classif_prime.get_params().items():
        value_orig = classifier.get_params()[param]
        if str(value_orig) != str(value_prime):
            raise ValueError('param values not equal for param %s: %s vs %s' % (param, value_orig, value_prime))

    task = openml.tasks.get_task(run.task_id)
    run_check = openml.runs.run_model_on_task(task, classif_prime)
    score = run_check.get_metric_score(sklearn.metrics.accuracy_score)
    print('%s [CHECK] Data: %s; Accuracy: %0.2f' % (openmlpimp.utils.get_time(), task.get_dataset().name, score.mean()))

    return True


if __name__ == '__main__':
    args = parse_args()
    openml.config.apikey = args.openml_apikey
    if args.openml_server:
        openml.config.server = args.openml_server

    configuration_space = get_configuration_space(
        info={'task': autosklearn.constants.MULTICLASS_CLASSIFICATION, 'is_sparse': 0},
        include_estimators=[args.classifier],
        include_preprocessors=['no_preprocessing'])

    if args.openml_taskid is None:
        study = openml.study.get_study(args.study_id, 'tasks')
        all_task_ids = study.tasks
        print("%s Obtained %d tasks: %s" %(openmlpimp.utils.get_time(), len(all_task_ids), all_task_ids))
        weighted_probabilities = get_probability_fn(configuration_space, all_task_ids)
        print(weighted_probabilities)

    for i in range(args.n_executions):
        try:
            if args.openml_taskid is None:
                # sample a weighted random task
                task_id = random.choice([val for val, cnt in weighted_probabilities.items() for i in range(cnt)])
            elif isinstance(args.openml_taskid, list):
                task_id = int(random.choice(args.openml_taskid))
            elif isinstance(args.openml_taskid, int):
                task_id = args.openml_taskid
            else:
                raise ValueError('Task id not given')
            # download task
            task = openml.tasks.get_task(task_id)

            data_name = task.get_dataset().name
            data_qualities = task.get_dataset().qualities
            print("%s Obtained task %d (%s); %s attributes; %s observations" %(openmlpimp.utils.get_time(), task_id, data_name,
                                                                               data_qualities['NumberOfFeatures'],
                                                                               data_qualities['NumberOfInstances']))

            indices = task.get_dataset().get_features_by_type('nominal', [task.target_name])

            classifier = openmlpimp.utils.obtain_classifier(configuration_space, indices)
            print(openmlpimp.utils.get_time(), classifier)

            # invoke OpenML run
            run = openml.runs.run_model_on_task(task, classifier)
            run.tags.append('openml-pimp')
            score = run.get_metric_fn(sklearn.metrics.accuracy_score)
            print('%s [SCORE] Data: %s; Accuracy: %0.2f' % (openmlpimp.utils.get_time(), task.get_dataset().name, score.mean()))

            # and publish it
            run.publish()
            print("%s Uploaded with run id %d" %(openmlpimp.utils.get_time(), run.run_id))

            # now do a check!
            # check_classifier_equals(run.run_id, classifier)
        except ValueError as e:
            traceback.print_exc()
        except TypeError as e:
            traceback.print_exc()
        except OpenMLServerException as e:
            traceback.print_exc()
        except Exception as e:
            traceback.print_exc()
